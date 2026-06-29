## 1. Memory Tool Injection

- [x] 1.1 Add conditional memory tool injection in `factory.py` `create_agent()` after A2A tools section (~line 299)
- [x] 1.2 Import `memory` from `strands_tools.memory` with try/except for graceful failure
- [x] 1.3 Pass `knowledge_base_id` explicitly to the memory tool function
- [x] 1.4 Add debug logging for memory tool injection (consistent with MCP/A2A logging)

## 2. Unit Tests

- [x] 2.1 Add test for memory tool injection when `enable_memory=True` and `knowledge_base_id` is set
- [x] 2.2 Add test for memory tool NOT injected when `enable_memory=False`
- [x] 2.3 Add test for memory tool NOT injected when `knowledge_base_id` is missing
- [x] 2.4 Add test for graceful handling when memory tool import fails
