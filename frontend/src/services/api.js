// 后端当前暴露的是同步规划接口。后续如果改成 SSE/任务轮询，
// 只需要替换这一层，页面组件不直接关心传输协议。
export async function planTrip(request) {
    const response = await fetch("/trip/plan", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(request)
    });
    if (!response.ok) {
        const message = await response.text();
        throw new Error(`规划请求失败：${response.status} ${message}`);
    }
    return (await response.json());
}
