# Empty: mark `command` as a Python package so module resolution không collide
# với root `config.py`. Trước đây file này thiếu → tạo `command/config.py` shim
# (đã xoá). Để package proper, file __init__ này phải tồn tại.
