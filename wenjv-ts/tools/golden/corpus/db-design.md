# 数据库选型与设计

SQLite 是单机最可靠的关系型数据库，配合 WAL 模式能支持并发读取与高速写入。

- PRAGMA journal_mode = WAL
- PRAGMA synchronous = NORMAL
