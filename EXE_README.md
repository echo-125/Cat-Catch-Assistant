# M3U8 下载器 - EXE 版本使用说明

## 📦 打包信息

- **文件名称**: `M3U8下载器.exe`
- **文件大小**: 约 15 MB
- **位置**: `dist/M3U8下载器.exe`
- **类型**: Windows 64位 GUI 应用程序（无控制台窗口）

## 🚀 使用方法

### 方式一：直接运行
双击 `dist/M3U8下载器.exe` 即可启动图形界面。

### 方式二：创建桌面快捷方式
1. 右键点击 `M3U8下载器.exe`
2. 选择"发送到" → "桌面快捷方式"
3. 以后可以从桌面直接启动

### 方式三：添加到开始菜单
1. 将 `M3U8下载器.exe` 复制到 `C:\Program Files\M3U8下载器\`
2. 创建快捷方式并放到开始菜单

## ⚙️ 系统要求

- **操作系统**: Windows 7/8/10/11 (64位)
- **依赖**: 无需安装 Python 或其他依赖，exe 已包含所有必要组件
- **可选**: ffmpeg（用于转换 MP4 格式）

## 📝 注意事项

### 1. 首次运行
- 首次运行会在 exe 同目录下创建 `config.json` 配置文件
- 配置文件会自动保存您的设置（下载路径、线程数等）

### 2. 杀毒软件误报
- 某些杀毒软件可能将打包的 exe 误报为病毒
- 这是 PyInstaller 打包程序的常见问题
- 解决方法：
  - 将 exe 添加到杀毒软件的白名单
  - 或使用代码签名证书对 exe 进行签名

### 3. 防火墙提示
- 首次运行时，Windows 防火墙可能会提示网络访问权限
- 请选择"允许访问"，否则无法下载视频

### 4. ffmpeg 支持
- exe 本身不包含 ffmpeg
- 如需转换为 MP4，请单独安装 ffmpeg 并添加到系统 PATH
- 下载地址: https://www.gyan.dev/ffmpeg/builds/

## 🔄 重新打包

如果修改了代码，需要重新打包：

```bash
# 方式一：使用打包脚本
python build_exe.py

# 方式二：直接使用 PyInstaller
pyinstaller M3U8下载器.spec
```

## 📂 文件结构

```
cat-catch-assistant/
├── dist/
│   └── M3U8下载器.exe          # 打包后的可执行文件
├── build/                        # 打包临时文件（可删除）
├── M3U8下载器.spec              # PyInstaller 配置文件
├── build_exe.py                  # 打包脚本
└── EXE_README.md                 # 本说明文档
```

## 🛠️ 高级配置

### 自定义图标
如果有 ico 图标文件，可以修改 `build_exe.py`：

```python
'--icon=icon.ico',  # 添加图标
```

### 减小文件体积
当前配置已排除不需要的模块。如需进一步优化：

1. 使用 UPX 压缩（需安装 UPX）：
   ```python
   '--upx-dir=/path/to/upx',
   ```

2. 使用 `--onedir` 代替 `--onefile`（生成文件夹而非单文件）

### 添加版本信息
创建 `version.txt`：

```
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(3,0,0,0),
    prodvers=(3,0,0,0),
    ...
  )
)
```

然后在打包时添加：
```python
'--version-file=version.txt',
```

## ❓ 常见问题

### Q1: 双击没反应？
- 检查是否被杀毒软件拦截
- 尝试以管理员身份运行
- 查看 Windows 事件查看器中的错误日志

### Q2: 提示缺少 DLL？
- 确保使用的是 64 位 Windows 系统
- 重新下载或重新打包 exe

### Q3: 配置文件保存在哪里？
- 配置文件保存在 exe 同目录下的 `config.json`
- 如果没有写入权限，会保存在用户目录

### Q4: 如何卸载？
- 直接删除 `M3U8下载器.exe` 和 `config.json` 即可
- 无需卸载程序，绿色便携

## 📊 打包参数说明

当前默认使用 `M3U8下载器.spec` 打包，关键配置如下：

- `name='M3U8下载器'`: 默认输出中文文件名
- `console=False`: 窗口模式，不显示控制台
- `datas=[('icon.ico', '.')]`: 打包应用图标
- `--clean`: 清理旧的构建缓存
- `--noconfirm`: 覆盖输出不询问

## 📝 更新日志

### v3.0 (2026-04-16)
- ✅ 首次打包为 exe
- ✅ 包含所有核心功能
- ✅ 支持多任务并行下载
- ✅ 支持断点续传
- ✅ 支持繁简转换

## 🙏 致谢

- PyInstaller - Python 打包工具
- 所有依赖库的开发者
