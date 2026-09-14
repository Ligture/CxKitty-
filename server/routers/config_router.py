"""配置路由"""

from fastapi import APIRouter, HTTPException, Request, Body

from server.services.config_service import ConfigService, SEARCHER_TEMPLATES

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config")
def get_config():
    """获取完整配置"""
    config = ConfigService.load()
    config.setdefault("searchers", [])
    config.setdefault("proxies", {"enable": False, "HTTP": "", "HTTPS": ""})
    config.setdefault("video", {"enable": True, "wait": 15, "speed": 1.0, "report_rate": 58})
    config.setdefault("work", {"enable": True, "export": True, "wait": 15, "fallback_fuzzer": False, "fallback_save": True})
    config.setdefault("document", {"enable": True, "wait": 15})
    config.setdefault("exam", {"fallback_fuzzer": False, "persubmit_delay": 15, "confirm_submit": True})
    return {"ok": True, "data": config}


@router.put("/config")
async def save_config(request: Request):
    """保存完整配置"""
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(400, "配置格式错误")
    ConfigService.save(data)
    try:
        await request.app.state.sio.emit("config:updated", {"message": "配置已更新"})
    except Exception:
        pass
    return {"ok": True, "message": "配置保存成功"}


@router.patch("/config/section/{section}")
async def save_config_section(section: str, request: Request):
    """保存配置 section (partial update)"""
    data = await request.json()
    if section == "searchers":
        if not isinstance(data, list):
            raise HTTPException(400, "searchers 应为数组")
        current = ConfigService.load()
        current["searchers"] = data
        ConfigService.save(current)
    else:
        ConfigService.patch_section(section, data)
    try:
        await request.app.state.sio.emit("config:updated", {"section": section})
    except Exception:
        pass
    return {"ok": True, "message": f"配置节 '{section}' 保存成功"}


@router.get("/searchers/templates")
def get_searcher_templates():
    """获取搜索器模板定义"""
    return {"ok": True, "data": SEARCHER_TEMPLATES}


@router.get("/searchers")
def get_searchers():
    """获取当前搜索器列表"""
    config = ConfigService.load()
    return {"ok": True, "data": config.get("searchers", [])}


@router.put("/searchers")
async def save_searchers(request: Request):
    """保存搜索器列表"""
    data = await request.json()
    if not isinstance(data, list):
        raise HTTPException(400, "应为数组")
    config = ConfigService.load()
    config["searchers"] = data
    ConfigService.save(config)
    try:
        await request.app.state.sio.emit("config:updated", {"section": "searchers"})
    except Exception:
        pass
    return {"ok": True, "message": "搜索器列表保存成功"}


@router.put("/searchers/{index}")
async def update_searcher(index: int, request: Request):
    """更新单个搜索器"""
    data = await request.json()
    config = ConfigService.load()
    searchers = config.get("searchers", [])
    if index < 0 or index >= len(searchers):
        raise HTTPException(400, "索引越界")
    searchers[index] = data
    config["searchers"] = searchers
    ConfigService.save(config)
    try:
        await request.app.state.sio.emit("config:updated", {"section": "searchers"})
    except Exception:
        pass
    return {"ok": True, "message": "搜索器已更新"}


@router.delete("/searchers/{index}")
async def delete_searcher(index: int, request: Request):
    """删除单个搜索器"""
    config = ConfigService.load()
    searchers = config.get("searchers", [])
    if index < 0 or index >= len(searchers):
        raise HTTPException(400, "索引越界")
    deleted = searchers.pop(index)
    config["searchers"] = searchers
    ConfigService.save(config)
    try:
        await request.app.state.sio.emit("config:updated", {"section": "searchers"})
    except Exception:
        pass
    return {"ok": True, "message": "搜索器已删除", "data": deleted}
