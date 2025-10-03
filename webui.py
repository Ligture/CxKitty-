#!/usr/bin/env python3
"""
CxKitty Web UI - 现代化网页界面
提供与原TUI相同的所有功能，采用现代设计理念
"""
import json
import os
import sys
for key in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    if key in os.environ:
        del os.environ[key]
import time
import threading
import base64
from pathlib import Path
from io import BytesIO
from typing import Optional

from flask import Flask, render_template, request, jsonify, session, send_file
from flask_socketio import SocketIO, emit
from qrcode import QRCode

import config
from cxapi import ChaoXingAPI, ChapterContainer, ClassSelector, ExamDto
from cxapi.exception import ChapterNotOpened, TaskPointError
from logger import Logger
from resolver import DocumetResolver, MediaPlayResolver, QuestionResolver
from utils import __version__, ck2dict, sessions_load, save_session, mask_name, mask_phone

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24).hex()
socketio = SocketIO(app, cors_allowed_origins="*")

logger = Logger("WebUI")

# 全局API实例字典，按session_id存储
api_instances = {}
task_threads = {}


def get_api(session_id: str) -> ChaoXingAPI:
    """获取或创建API实例"""
    if session_id not in api_instances:
        api_instances[session_id] = ChaoXingAPI()
    return api_instances[session_id]


@app.route('/')
def index():
    """主页"""
    return render_template('index.html', version=__version__)


@app.route('/api/version')
def get_version():
    """获取版本信息"""
    return jsonify({
        'version': __version__,
        'status': 'ok'
    })


@app.route('/api/sessions')
def get_sessions():
    """获取保存的会话列表"""
    sessions = sessions_load()
    return jsonify({
        'sessions': [
            {
                'phone': mask_phone(s.phone) if config.MASKACC else s.phone,
                'puid': s.puid,
                'name': mask_name(s.name) if config.MASKACC else s.name,
            }
            for s in sessions
        ]
    })


@app.route('/api/login/password', methods=['POST'])
def login_password():
    """手机号密码登录"""
    data = request.json
    phone = data.get('phone')
    password = data.get('password')
    
    if not phone or not password:
        return jsonify({'success': False, 'message': '手机号和密码不能为空'}), 400
    
    session_id = session.get('session_id', os.urandom(16).hex())
    session['session_id'] = session_id
    
    api = get_api(session_id)
    status, result = api.login_passwd(phone, password)
    
    if status:
        api.accinfo()
        save_session(api.session.ck_dump(), api.acc, password)
        return jsonify({
            'success': True,
            'account': {
                'puid': api.acc.puid,
                'name': api.acc.name,
                'sex': api.acc.sex.name,
                'phone': api.acc.phone,
                'school': api.acc.school,
                'stu_id': api.acc.stu_id
            }
        })
    else:
        return jsonify({'success': False, 'message': result.get('msg', '登录失败')}), 401


@app.route('/api/login/qr/init', methods=['POST'])
def qr_login_init():
    """初始化二维码登录"""
    session_id = session.get('session_id', os.urandom(16).hex())
    session['session_id'] = session_id
    
    api = get_api(session_id)
    api.qr_get()
    qr_url = api.qr_geturl()
    
    # 生成二维码图片
    qr = QRCode()
    qr.add_data(qr_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    # 转换为base64
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    return jsonify({
        'success': True,
        'qr_image': f'data:image/png;base64,{img_str}'
    })


@app.route('/api/login/qr/check', methods=['POST'])
def qr_login_check():
    """检查二维码登录状态"""
    session_id = session.get('session_id')
    if not session_id:
        return jsonify({'success': False, 'message': '会话不存在'}), 400
    
    api = get_api(session_id)
    qr_status = api.login_qr()
    
    if qr_status['status']:
        api.accinfo()
        save_session(api.session.ck_dump(), api.acc)
        return jsonify({
            'success': True,
            'status': 'success',
            'account': {
                'puid': api.acc.puid,
                'name': api.acc.name,
                'sex': api.acc.sex.name,
                'phone': api.acc.phone,
                'school': api.acc.school,
                'stu_id': api.acc.stu_id
            }
        })
    
    qr_type = qr_status.get('type')
    if qr_type == '1':
        return jsonify({'success': False, 'status': 'error', 'message': '二维码验证错误'})
    elif qr_type == '2':
        return jsonify({'success': False, 'status': 'expired', 'message': '二维码已失效'})
    elif qr_type == '4':
        return jsonify({
            'success': True, 
            'status': 'scanned', 
            'message': f"已扫描: {qr_status.get('nickname', '')}",
            'nickname': qr_status.get('nickname', '')
        })
    
    return jsonify({'success': True, 'status': 'waiting', 'message': '等待扫描'})


@app.route('/api/login/session', methods=['POST'])
def login_session():
    """使用保存的会话登录"""
    data = request.json
    puid = data.get('puid')
    
    if not puid:
        return jsonify({'success': False, 'message': 'puid不能为空'}), 400
    
    sessions = sessions_load()
    target_session = None
    for s in sessions:
        if s.puid == puid:
            target_session = s
            break
    
    if not target_session:
        return jsonify({'success': False, 'message': '会话不存在'}), 404
    
    session_id = session.get('session_id', os.urandom(16).hex())
    session['session_id'] = session_id
    
    api = get_api(session_id)
    ck = ck2dict(target_session.ck)
    api.session.ck_load(ck)
    
    if not api.accinfo():
        return jsonify({'success': False, 'message': '会话已失效，请重新登录'}), 401
    
    return jsonify({
        'success': True,
        'account': {
            'puid': api.acc.puid,
            'name': api.acc.name,
            'sex': api.acc.sex.name,
            'phone': api.acc.phone,
            'school': api.acc.school,
            'stu_id': api.acc.stu_id
        }
    })


@app.route('/api/classes')
def get_classes():
    """获取课程列表"""
    session_id = session.get('session_id')
    if not session_id:
        return jsonify({'success': False, 'message': '未登录'}), 401
    
    api = get_api(session_id)
    
    # 拉取人脸图片
    if config.FETCH_UPLOADED_FACE:
        if face_url := api.fetch_face():
            api.save_face(face_url, config.FACE_PATH)
    
    classes = api.fetch_classes()
    
    return jsonify({
        'success': True,
        'classes': [
            {
                'index': idx,
                'course_id': cls.course_id,
                'class_id': cls.class_id,
                'name': cls.name,
                'teacher': cls.teacher_name,
                #'image': cls.image,
                'status': cls.state.name,
                #'is_exam': cls.is_exam
            }
            for idx, cls in enumerate(classes.classes)

        ]
    })


@app.route('/api/class/<int:class_index>/chapters')
def get_chapters(class_index):
    """获取课程章节"""
    session_id = session.get('session_id')
    if not session_id:
        return jsonify({'success': False, 'message': '未登录'}), 401
    
    api = get_api(session_id)
    classes = api.fetch_classes()
    
    if class_index >= len(classes):
        return jsonify({'success': False, 'message': '课程不存在'}), 404
    
    target_class = classes[class_index]
    chapter = api.fetch_chapters(
        course_id=target_class.course_id,
        class_id=target_class.class_id
    )
    
    # 递归解析章节树
    def parse_chapter_tree(chap_list):
        result = []
        for chap in chap_list:
            item = {
                'id': chap.id,
                'name': chap.name,
                'is_leaf': chap.is_leaf,
                'status': chap.status.name if hasattr(chap, 'status') else 'UNKNOWN',
                'point_total': chap.point_total if hasattr(chap, 'point_total') else 0,
                'point_finished': chap.point_finished if hasattr(chap, 'point_finished') else 0,
            }
            if hasattr(chap, 'layers') and chap.layers:
                item['children'] = parse_chapter_tree(chap.layers)
            result.append(item)
        return result
    
    return jsonify({
        'success': True,
        'chapter': {
            'name': chapter.name,
            'course_id': chapter.course_id,
            'class_id': chapter.class_id,
            'chapters': parse_chapter_tree(chapter.layers)
        }
    })


@app.route('/api/task/start', methods=['POST'])
def start_task():
    """开始任务"""
    session_id = session.get('session_id')
    if not session_id:
        return jsonify({'success': False, 'message': '未登录'}), 401
    
    data = request.json
    class_indices = data.get('class_indices', [])
    
    if not class_indices:
        return jsonify({'success': False, 'message': '未选择课程'}), 400
    
    # 在新线程中执行任务
    task_id = os.urandom(16).hex()
    thread = threading.Thread(
        target=execute_tasks,
        args=(session_id, class_indices, task_id)
    )
    task_threads[task_id] = thread
    thread.start()
    
    return jsonify({
        'success': True,
        'task_id': task_id,
        'message': '任务已开始'
    })


def execute_tasks(session_id: str, class_indices: list, task_id: str):
    """执行任务的后台线程"""
    try:
        socketio.emit('task_event', {
            'task_id': task_id,
            'type': 'start',
            'message': '任务开始执行'
        }, namespace='/')
        
        api = get_api(session_id)
        classes = api.fetch_classes()
        
        # 构建选择器命令
        command = ','.join(str(idx) for idx in class_indices)
        
        # 注册回调
        def on_captcha_after(times: int):
            socketio.emit('task_event', {
                'task_id': task_id,
                'type': 'captcha',
                'message': f'正在识别验证码，第 {times} 次...'
            }, namespace='/')
        
        def on_captcha_before(status: bool, code: str):
            if status:
                socketio.emit('task_event', {
                    'task_id': task_id,
                    'type': 'captcha_success',
                    'message': f'验证码识别成功：{code}'
                }, namespace='/')
            else:
                socketio.emit('task_event', {
                    'task_id': task_id,
                    'type': 'captcha_failed',
                    'message': f'验证码识别失败：{code}'
                }, namespace='/')
        
        def on_face_detection_after(orig_url):
            socketio.emit('task_event', {
                'task_id': task_id,
                'type': 'face_detection',
                'message': '开始人脸识别'
            }, namespace='/')
        
        def on_face_detection_before(object_id: str, image_path):
            socketio.emit('task_event', {
                'task_id': task_id,
                'type': 'face_detection_success',
                'message': '人脸识别成功'
            }, namespace='/')
        
        api.session.reg_captcha_after(on_captcha_after)
        api.session.reg_captcha_before(on_captcha_before)
        api.session.reg_face_after(on_face_detection_after)
        api.session.reg_face_before(on_face_detection_before)
        
        # 执行任务
        for task_obj in ClassSelector(command, classes):
            if isinstance(task_obj, ChapterContainer):
                socketio.emit('task_event', {
                    'task_id': task_id,
                    'type': 'chapter_start',
                    'message': f'📚 开始处理课程：{task_obj.name}'
                }, namespace='/')
                
                try:
                    process_chapter_tasks(task_obj, task_id)
                    
                    socketio.emit('task_event', {
                        'task_id': task_id,
                        'type': 'chapter_complete',
                        'message': f'✓ 课程完成：{task_obj.name}'
                    }, namespace='/')
                except Exception as e:
                    socketio.emit('task_event', {
                        'task_id': task_id,
                        'type': 'error',
                        'message': f'✗ 课程处理失败：{task_obj.name} - {str(e)}'
                    }, namespace='/')
                    print(e)
            
            elif isinstance(task_obj, ExamDto):
                socketio.emit('task_event', {
                    'task_id': task_id,
                    'type': 'exam_start',
                    'message': '📝 开始考试模式'
                }, namespace='/')
                try:
                    process_exam(task_obj, task_id)
                except Exception as e:
                    socketio.emit('task_event', {
                        'task_id': task_id,
                        'type': 'error',
                        'message': f'✗ 考试处理失败: {str(e)}'
                    }, namespace='/')
            
            elif isinstance(task_obj, list):
                # 考试列表，需要用户选择
                socketio.emit('task_event', {
                    'task_id': task_id,
                    'type': 'exam_list',
                    'message': f'📋 发现 {len(task_obj)} 个考试，请在设置中配置考试处理',
                    'exams': [
                        {
                            'title': exam.title if hasattr(exam, 'title') else '未知',
                            'exam_id': exam.exam_id if hasattr(exam, 'exam_id') else 0,
                            'status': exam.status.name if hasattr(exam, 'status') else 'UNKNOWN'
                        } for exam in task_obj
                    ]
                }, namespace='/')
        
        socketio.emit('task_event', {
            'task_id': task_id,
            'type': 'complete',
            'message': '✓ 所有任务已完成'
        }, namespace='/')
        
    except Exception as e:
        logger.error(f"任务执行异常: {e}", exc_info=True)
        socketio.emit('task_event', {
            'task_id': task_id,
            'type': 'error',
            'message': f'✗ 任务执行出错: {str(e)}'
        }, namespace='/')
    finally:
        # 清理任务线程
        if task_id in task_threads:
            del task_threads[task_id]


def process_exam(exam: ExamDto, task_id: str):
    """处理考试任务"""
    try:

        
        # 拉取元数据
        exam.get_meta()
        socketio.emit('task_event', {
            'task_id': task_id,
            'type': 'exam_info',
            'message': f'考试：{exam.title}'
        }, namespace='/')
        # 开始考试
        exam.start()
        
        socketio.emit('task_event', {
            'task_id': task_id,
            'type': 'exam_started',
            'message': f'考试已开始，剩余时间：{exam.remain_time_str}'
        }, namespace='/')
        
        # 定义答题回调函数
        def on_question_progress(index, total, completed, incompleted, question, answer_status):
            """答题进度回调"""
            socketio.emit('task_event', {
                'task_id': task_id,
                'type': 'question_progress',
                'message': f'答题进度: {index + 1}/{total}',
                'data': {
                    'index': index,
                    'total': total,
                    'completed': completed,
                    'incompleted': incompleted,
                    'question': {
                        'id': question.id,
                        'type': question.type.name,
                        'value': question.value[:50] + '...' if len(question.value) > 50 else question.value,
                        'answer': str(question.answer) if answer_status else '未匹配'
                    },
                    'answer_status': answer_status
                }
            }, namespace='/')
        
        def on_question_submit(index, question, is_success, result_data):
            """答题提交回调"""
            socketio.emit('task_event', {
                'task_id': task_id,
                'type': 'question_submit',
                'message': f'提交{"成功" if is_success else "失败"}: 第{index + 1}题',
                'data': {
                    'index': index,
                    'is_success': is_success,
                    'result': result_data
                }
            }, namespace='/')
        
        # 实例化解决器
        resolver = QuestionResolver(
            exam_dto=exam,
            fallback_save=False,
            fallback_fuzzer=config.EXAM.get("fallback_fuzzer", False),
            persubmit_delay=config.EXAM.get("persubmit_delay", 15),
            cb_progress=on_question_progress,
            cb_submit=on_question_submit
        )
        
        # 执行答题
        resolver.execute()
        
        socketio.emit('task_event', {
            'task_id': task_id,
            'type': 'exam_complete',
            'message': '考试完成'
        }, namespace='/')
        
    except Exception as e:
        logger.error(f"考试处理异常: {e}", exc_info=True)
        socketio.emit('task_event', {
            'task_id': task_id,
            'type': 'error',
            'message': f'考试处理出错: {str(e)}'
        }, namespace='/')


def process_chapter_tasks(chapter: ChapterContainer, task_id: str):
    """处理章节任务"""
    try:
        #拉取最新状态
        chapter.fetch_point_status()
        for chapter_index in range(len(chapter)):
            layer = chapter.chapters[chapter_index]
            socketio.emit('task_event', {
                'task_id': task_id,
                'type': 'info',
                'message': f'检查章节：{layer.name}'
            }, namespace='/')

            refresh_flag = True
            for task_point in chapter[chapter_index]:
                try:
                    task_point.fetch_attachment()

                except ChapterNotOpened:
                    if refresh_flag:
                        chapter.refresh_chapter(chapter_index - 1)
                        refresh_flag = False
                        continue
                    else:
                        socketio.emit('task_event', {
                            'task_id': task_id,
                            'type': 'warning',
                            'message': f'⚠ 章节未开放：{layer.name}'
                        }, namespace='/')
                        continue
                refresh_flag = True

                task_type = task_point.__class__.__name__
                
                try:
                    # 视频任务
                    if config.VIDEO_EN and task_type == 'PointVideoDto':
                        if not task_point.parse_attachment():
                            continue
                        # 拉取任务点数据
                        if not task_point.fetch():
                            continue
                        socketio.emit('task_event', {
                            'task_id': task_id,
                            'type': 'task_point_start',
                            'message': f'处理任务点： {task_point.title} [{task_type}]'
                        }, namespace='/')

                        # 创建带WebSocket回调的视频解决器
                        def on_video_progress(playing_time, duration, speed, next_report_time):
                            """视频播放进度回调"""
                            socketio.emit('task_event', {
                                'task_id': task_id,
                                'type': 'video_progress',
                                'message': f'播放中： {task_point.title}',
                                'data': {
                                    'title': task_point.title,
                                    'current_time': playing_time,
                                    'duration': duration,
                                    'speed': speed,
                                    'next_report': next_report_time,
                                    'progress_percent': round(playing_time / duration * 100, 1) if duration > 0 else 0
                                }
                            }, namespace='/')
                        
                        def on_video_report(playing_time, duration, is_success, result_data=None):
                            """视频上报回调"""
                            socketio.emit('task_event', {
                                'task_id': task_id,
                                'type': 'video_report',
                                'message': f'上报{"成功" if is_success else "失败"}: {playing_time}/{duration}秒',
                                'data': {
                                    'playing_time': playing_time,
                                    'duration': duration,
                                    'is_success': is_success,
                                    'result': result_data
                                }
                            }, namespace='/')
                        
                        resolver = MediaPlayResolver(
                            media_dto=task_point,
                            speed=config.VIDEO["speed"],
                            report_rate=config.VIDEO["report_rate"],
                            cb_progress=on_video_progress,
                            cb_report=on_video_report
                        )
                        resolver.execute()
                        socketio.emit('task_event', {
                            'task_id': task_id,
                            'type': 'info',
                            'message': f'视频任务完成，等待 {config.VIDEO_WAIT} 秒'
                        }, namespace='/')
                        time.sleep(config.VIDEO_WAIT)
                    
                    # 文档任务
                    elif config.DOCUMENT_EN and task_type == 'PointDocumentDto':
                        if not task_point.parse_attachment():
                            continue
                        socketio.emit('task_event', {
                            'task_id': task_id,
                            'type': 'task_point_start',
                            'message': f'处理任务点： {task_point.title} [{task_type}]'
                        }, namespace='/')
                        resolver = DocumetResolver(document_dto=task_point)
                        resolver.execute()
                        socketio.emit('task_event', {
                            'task_id': task_id,
                            'type': 'info',
                            'message': f'文档任务完成，等待 {config.DOCUMENT_WAIT} 秒'
                        }, namespace='/')
                        time.sleep(config.DOCUMENT_WAIT)
                    
                    # 作业/测验任务
                    elif (config.WORK_EN or config.WORK["export"] is True) and task_type == 'PointWorkDto':

                        if config.WORK["export"] is True:
                            task_point.parse_attachment()
                            # 保存 json 文件
                            task_point.export(
                                config.EXPORT_PATH / f"work_{task_point.work_id}.json"
                            )
                        if config.WORK_EN:
                            if not task_point.parse_attachment():
                                continue
                            task_point.fetch_all()
                            socketio.emit('task_event', {
                                'task_id': task_id,
                                'type': 'task_point_start',
                                'message': f'处理任务点： {task_point.title} [{task_type}]'
                            }, namespace='/')
                            # 定义作业答题回调函数
                            def on_work_progress(index, total, completed, incompleted, question, answer_status):
                                """作业答题进度回调"""
                                socketio.emit('task_event', {
                                    'task_id': task_id,
                                    'type': 'question_progress',
                                    'message': f'答题进度: {index + 1}/{total}',
                                    'data': {
                                        'index': index,
                                        'total': total,
                                        'completed': completed,
                                        'incompleted': incompleted,
                                        'question': {
                                            'id': question.id,
                                            'type': question.type.name,
                                            'value': question.value[:50] + '...' if len(question.value) > 50 else question.value,
                                            'answer': str(question.answer) if answer_status else '未匹配'
                                        },
                                        'answer_status': answer_status
                                    }
                                }, namespace='/')
                            
                            def on_work_submit(index, question, is_success, result_data):
                                """作业答题提交回调"""
                                socketio.emit('task_event', {
                                    'task_id': task_id,
                                    'type': 'question_submit',
                                    'message': f'提交{"成功" if is_success else "失败"}: 第{index + 1}题',
                                    'data': {
                                        'index': index,
                                        'is_success': is_success,
                                        'result': result_data
                                    }
                                }, namespace='/')
                            
                            resolver = QuestionResolver(
                                exam_dto=task_point,
                                fallback_save=config.WORK["fallback_save"],
                                fallback_fuzzer=config.WORK["fallback_fuzzer"],
                                cb_progress=on_work_progress,
                                cb_submit=on_work_submit
                            )
                            resolver.execute()
                            socketio.emit('task_event', {
                                'task_id': task_id,
                                'type': 'info',
                                'message': f'作业任务完成，等待 {config.WORK_WAIT} 秒'
                            }, namespace='/')
                            time.sleep(config.WORK_WAIT)


                    
                    socketio.emit('task_event', {
                        'task_id': task_id,
                        'type': 'task_point_complete',
                        'message': f'✓ 任务点完成： {task_point.title}'
                    }, namespace='/')

                except Exception as e:
                    # 使用 getattr 安全地获取 title，如果不存在则使用一个默认的名称
                    task_title = getattr(task_point, 'title', '未知任务点')
                    socketio.emit('task_event', {
                        'task_id': task_id,
                        'type': 'error',
                        'message': f'✗ 任务点处理失败： {task_title} - {str(e)}'
                    }, namespace='/')
            
            # 刷新状态
            chapter.fetch_point_status()
            socketio.emit('task_event', {
                'task_id': task_id,
                'type': 'info',
                'message': f'章节状态已更新：{layer.name}'
            }, namespace='/')

    except Exception as e:
        logger.error(f"章节任务处理异常: {e}", exc_info=True)
        socketio.emit('task_event', {
            'task_id': task_id,
            'type': 'error',
            'message': f'章节处理异常：{str(e)}'
        }, namespace='/')
        raise


@app.route('/api/config')
def get_config():
    """获取配置信息"""
    return jsonify({
        'success': True,
        'config': {
            'video': {
                'enable': config.VIDEO_EN,
                'wait': config.VIDEO_WAIT
            },
            'work': {
                'enable': config.WORK_EN,
                'wait': config.WORK_WAIT,
                'fallback_fuzzer': config.WORK.get('fallback_fuzzer', False),
                'fallback_save': config.WORK.get('fallback_save', True)
            },
            'document': {
                'enable': config.DOCUMENT_EN,
                'wait': config.DOCUMENT_WAIT
            },
            'exam': {
                'fallback_fuzzer': config.EXAM.get('fallback_fuzzer', False),
                'confirm_submit': config.EXAM.get('confirm_submit', True)
            }
        }
    })


@socketio.on('connect')
def handle_connect():
    """WebSocket连接"""
    logger.info('WebSocket客户端已连接')
    emit('connected', {'message': '已连接到服务器'})


@socketio.on('disconnect')
def handle_disconnect():
    """WebSocket断开"""
    logger.info('WebSocket客户端已断开')


if __name__ == '__main__':
    logger.info(f"CxKitty Web UI v{__version__} 启动")
    logger.info("访问 http://127.0.0.1:5000 使用Web界面")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False,allow_unsafe_werkzeug=True)
