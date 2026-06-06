"""LLM 推理型 agent。

这个包只放需要模型参与的任务。Graph node 和业务 service 不应直接调用具体 SDK，
而是通过这里的 agent 或更底层的 LLM client 完成结构化推理。
"""
