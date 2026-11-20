"""大模型调用的 JSON Schema 定义，涵盖三大复合工具：pw_page, pw_interact, pw_media。"""

PW_PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["open", "read", "search", "switch_tab", "dialog", "close"],
            "description": "要执行的页面动作：open(打开网址), read(读取页面快照), search(关键词搜索), switch_tab(切换标签页), dialog(响应弹窗), close(关闭当前浏览器上下文)",
        },
        "url": {
            "type": "string",
            "description": "网页地址 (action='open' 时必填)",
        },
        "page": {
            "type": "integer",
            "description": "分页查看时的页码编号，从1开始 (action='read' 时可选，默认为1)",
        },
        "target": {
            "type": "string",
            "enum": ["all", "text", "elements"],
            "description": "查看或搜索的目标范围：'all'(全部正文与可交互元素), 'text'(仅正文段落), 'elements'(仅可交互操作元素) (action='read' 或 'search' 时可选，默认为'all')",
        },
        "keyword": {
            "type": "string",
            "description": "页面内容搜索关键词 (action='search' 时必填)",
        },
        "tab_index": {
            "type": "integer",
            "description": "要切换到的标签页序号 (action='switch_tab' 时必填)",
        },
        "dialog_action": {
            "type": "string",
            "enum": ["accept", "dismiss"],
            "description": "弹窗响应行为：'accept'(确认/确定) 或 'dismiss'(取消/拒绝) (action='dialog' 时必填)",
        },
        "prompt_text": {
            "type": "string",
            "description": "Prompt 弹窗的输入文本 (action='dialog' 且为 prompt 时可选)",
        },
    },
    "required": ["action"],
}

PW_INTERACT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["click", "fill", "select", "hover", "focus", "blur", "drag", "press_key", "scroll"],
            "description": "要执行的交互动作：click(点击元素), fill(输入文本), select(下拉框选择), hover(鼠标悬停), focus(聚焦), blur(失焦), drag(拖拽至目标元素), press_key(按键盘按键), scroll(滚动页面)",
        },
        "ref": {
            "type": "integer",
            "description": "目标元素在页面快照中的 Ref ID 编号 (除 press_key/scroll 外通常必填)",
        },
        "text": {
            "type": "string",
            "description": "输入文本内容 (action='fill' 时必填)",
        },
        "value": {
            "type": "string",
            "description": "下拉框选中的选项值 (action='select' 时必填)",
        },
        "target_ref": {
            "type": "integer",
            "description": "拖拽放置的目标元素 Ref ID 编号 (action='drag' 时必填)",
        },
        "key": {
            "type": "string",
            "description": "要发送的按键名称，如 'Enter', 'Escape', 'Tab', 'ArrowDown' 等 (action='press_key' 时必填)",
        },
        "direction": {
            "type": "string",
            "enum": ["down", "up"],
            "description": "滚动方向：'down'(向下) 或 'up'(向上) (action='scroll' 时可选，默认为'down')",
        },
        "amount": {
            "type": "integer",
            "description": "滚动像素距离 (action='scroll' 时可选，默认为 500)",
        },
    },
    "required": ["action"],
}

PW_MEDIA_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["screenshot_viewport", "screenshot_full", "download"],
            "description": "要执行的媒体动作：screenshot_viewport(当前视口截图), screenshot_full(全页面长截图), download(触发下载指定元素文件)",
        },
        "target": {
            "type": "string",
            "enum": ["chat", "ai"],
            "description": "截图交付目标：'chat'(直接发送至聊天供用户查看) 或 'ai'(返回 base64 供大模型分析) (截图类动作可选，默认 'chat')",
        },
        "ref": {
            "type": "integer",
            "description": "下载按钮或链接的 Ref ID 编号 (action='download' 时必填)",
        },
    },
    "required": ["action"],
}
