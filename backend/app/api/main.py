from __future__ import annotations

# 导入 FastAPI 主类，用来创建后端应用实例
from fastapi import FastAPI

# 导入 CORS 中间件，用来解决前端跨域请求问题
from fastapi.middleware.cors import CORSMiddleware

# 导入不同模块下的路由
# compat：兼容旧接口或旧版本 API
# export：导出相关接口，例如 PDF 导出
# plans：方案相关接口，例如查询、收藏、详情
# trip：行程规划主接口
from app.api.routes import compat, export, plans, trip
from app.bus.subscribers import install_frontend_progress_subscriber
from app.runtime.runtime_paths import ensure_runtime_dirs

# 在函数启动之前, 先确认运行时所需要的目录是否存在
ensure_runtime_dirs()

# 启动前端进度订阅器，让 bus 事件可以被前端监听到
install_frontend_progress_subscriber()

# 创建 FastAPI 应用实例
# title 会显示在接口文档页面中
# version 表示当前 API 版本
app = FastAPI(title="LifeRouteAgent API", version="0.1.0")


# 给 FastAPI 应用添加 CORS 跨域中间件, 作用：允许前端开发服务器访问后端接口
app.add_middleware(
    CORSMiddleware,
    # 允许访问后端的前端地址列表, Vite 默认开发端口通常是 5173
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    # 是否允许携带 Cookie、Authorization 等凭证信息
    allow_credentials=True,
    # 允许所有 HTTP 方法. 例如 GET、POST、PUT、DELETE、OPTIONS 等
    allow_methods=["*"],
    # 允许所有请求头 例如 Content-Type、Authorization 等
    allow_headers=["*"],
)


# 注册行程规划相关路由
app.include_router(trip.router)

# 注册方案管理相关路由, 例如方案详情、方案列表、方案保存等接口
app.include_router(plans.router)

# 注册导出相关路由, 例如导出 PDF、导出行程文件等接口
app.include_router(export.router)

# 注册兼容旧版本的接口路由, 用于兼容之前前端或旧 API 调用方式
app.include_router(compat.router)


@app.get("/health")
def health() -> dict[str, str]:
    """
    定义健康检查接口, 访问 GET /health 时，会返回 {"status": "ok"} 通常用于检查后端服务是否正常启动
    :return:
    """
    # 返回服务状态
    return {"status": "ok"}


# 定义一个本地调试函数
# 作用：不通过 HTTP 接口，直接在 Python 代码里运行一次规划流程
def run_once(user_query: str) -> dict:
    # 导入规划图执行函数
    # 放在函数内部导入，可以避免应用启动时就加载完整规划模块
    from app.planning.graph_builder import run_planning_request

    # 导入状态转换函数
    # 作用：把新的 PlanningState 转换成旧版接口兼容的 dict 格式
    from app.planning.state import planning_state_to_legacy

    # 执行规划请求，并把结果转换成旧版返回格式
    return planning_state_to_legacy(run_planning_request(user_query))


# 当这个文件被直接运行时，执行下面的代码
# 例如：python main.py
# 如果是通过 uvicorn 启动，则不会执行这里
if __name__ == "__main__":
    # 使用一条测试输入，直接跑一次规划流程
    result = run_once("周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元")

    # 打印规划结果中的回复文本
    print(result["response_text"])
