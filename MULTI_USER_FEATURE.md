# 多用户登录功能实现说明

## 功能概述

本次更新为 CxKitty Web UI 添加了完整的多用户登录和管理功能，允许用户在单个浏览器窗口中同时管理多个超星学习通账号。

## 核心功能

### 1. 多用户登录
- 支持同时登录多个账号
- 三种登录方式都支持多用户（密码、二维码、会话）
- 自动检测重复登录并更新会话

### 2. 用户切换
- 点击用户切换器查看所有已登录用户
- 一键切换到其他账号
- 切换时自动刷新课程列表
- 切换时清空课程选择状态

### 3. 独立会话管理
- 每个用户拥有独立的 session_id
- API 实例按用户隔离
- 任务执行相互独立

### 4. 用户退出
- 可单独退出任意用户
- 支持退出当前活跃用户
- 最后一个用户退出时返回登录页

## 技术实现

### 后端 (webui.py)

#### 新增的全局变量
```python
logged_in_users = {}  # {flask_session_id: [user_info, ...]}
```

#### 新增的 API 端点

1. **GET /api/users/list**
   - 获取当前已登录的所有用户
   - 返回用户列表和当前活跃用户

2. **POST /api/users/switch**
   - 切换当前活跃用户
   - 参数：`session_id` (目标用户的session_id)

3. **POST /api/users/logout**
   - 退出指定用户
   - 参数：`session_id` (要退出的用户的session_id)

#### 修改的端点
- `/api/login/password` - 支持多用户登录
- `/api/login/qr/init` - 使用临时session
- `/api/login/qr/check` - 支持多用户登录
- `/api/login/session` - 支持多用户登录
- `/api/classes` - 使用 current_user_session_id
- `/api/class/<int:class_index>/chapters` - 使用 current_user_session_id
- `/api/task/start` - 使用 current_user_session_id

### 前端 (app.js)

#### 新增的状态变量
```javascript
this.loggedInUsers = [];  // 存储所有已登录的用户
```

#### 新增的方法

1. **loadLoggedInUsers()**
   - 从后端加载已登录用户列表
   - 更新当前用户状态

2. **updateUserSwitcher()**
   - 更新用户切换器 UI
   - 显示用户数量徽章
   - 渲染用户列表

3. **switchUser(sessionId)**
   - 切换到指定用户
   - 刷新课程列表
   - 清空选择状态

4. **logoutUser(sessionId)**
   - 退出指定用户
   - 更新用户列表
   - 处理最后一个用户退出的情况

5. **updateUserUI()**
   - 更新用户信息显示
   - 显示/隐藏相关元素

#### 修改的方法
- **onLoginSuccess()** - 加载用户列表并更新切换器
- **logout()** - 调用 logoutUser() 退出当前用户
- **loadCourses()** - 显示当前用户指示器

### UI/样式 (style.css)

#### 新增的样式类

1. **用户切换器**
   - `.user-switcher` - 主容器
   - `.user-switcher-btn` - 切换器按钮
   - `.user-switcher-dropdown` - 下拉菜单
   - `.user-count-badge` - 用户数量徽章

2. **用户列表**
   - `.user-switcher-header` - 列表头部
   - `.user-switch-item` - 用户项
   - `.user-switch-item.active` - 活跃用户高亮
   - `.active-indicator` - 当前用户标识

3. **用户信息**
   - `.user-switch-info` - 用户信息容器
   - `.user-switch-name` - 用户名
   - `.user-switch-meta` - 用户元信息

4. **操作按钮**
   - `.user-logout-btn` - 退出按钮
   - `.btn-add-user` - 添加用户按钮
   - `.user-switcher-footer` - 底部操作区

5. **当前用户指示器**
   - `.current-user-indicator` - 课程页用户指示器
   - `.pulse` 动画 - 脉动效果

6. **功能标识**
   - `.feature-badge` - 登录页功能标识

### HTML (index.html)

#### 新增的元素

1. 登录页面：
```html
<div class="feature-badge">
    <svg>...</svg>
    支持多用户同时登录
</div>
```

2. 课程页面：
```html
<p class="current-user-indicator" id="current-user-indicator"></p>
```

## 用户体验优化

### 视觉反馈
- 用户数量徽章：显示已登录用户数
- 活跃用户高亮：在切换器中标识当前用户
- 脉动指示器：课程页显示当前用户
- 平滑动画：所有交互都有过渡效果

### 交互优化
- 点击外部关闭下拉菜单
- 切换用户时显示加载提示
- 重复登录时更新会话而非创建新用户
- 支持键盘导航和屏幕阅读器

### 状态管理
- 自动刷新课程列表
- 清空课程选择状态
- 保持任务隔离
- 正确处理边界情况

## 测试建议

### 功能测试
1. 登录多个不同的账号
2. 在用户之间切换
3. 查看课程列表是否正确切换
4. 单独退出某个用户
5. 退出最后一个用户

### 边界测试
1. 重复登录同一个账号
2. 在执行任务时切换用户
3. 网页关闭后重新打开
4. 同时在多个浏览器标签页登录

### UI测试
1. 单个用户登录的显示效果
2. 多个用户登录的显示效果
3. 移动端响应式效果
4. 动画和过渡效果

## 未来改进方向

1. **持久化支持**
   - 将多用户状态保存到本地存储
   - 页面刷新后恢复用户列表

2. **任务管理增强**
   - 显示每个用户的任务状态
   - 支持同时为多个用户执行任务

3. **用户分组**
   - 支持用户分组管理
   - 批量操作多个用户

4. **更多状态信息**
   - 显示用户的在线时长
   - 显示最后活动时间
   - 显示任务完成情况

## 总结

本次更新成功实现了多用户登录和管理功能，大幅提升了 Web UI 的实用性。用户现在可以：
- 在一个页面中管理多个账号
- 快速切换账号而无需重新登录
- 独立管理每个账号的课程和任务
- 享受流畅的用户体验和现代化的界面

所有功能都经过精心设计，确保了代码的可维护性和扩展性。
