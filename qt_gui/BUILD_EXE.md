# Qt GUI 打包为 Windows EXE 指令

目标：生成可分享的 Windows 版本，优先保证体积小、启动快、默认路径可迁移。

推荐发布形式是 `portable/SemiUtilsQt/` 文件夹压缩包。入口仍然是 `SemiUtilsQt.exe`，但不使用单文件 exe；单文件 exe 每次启动通常需要解压运行库，启动更慢，也不利于保留可编辑的 `config.yaml`。把发布文件夹压缩后分享，用户解压后双击 `SemiUtilsQt.exe` 即可运行。

## 快速方式

推荐先激活项目使用的 conda 环境：

```powershell
conda activate semi-utils
.\build_release.bat
```

也可以直接双击或执行：

```powershell
.\build_release.bat
```

脚本会自动：

- 以 `build_release.bat` 所在的 `qt_gui` 文件夹作为构建根目录
- 优先使用已有 Python 环境：`BUILD_PYTHON` 指定值、已激活的 conda 环境、名为 `semi-utils` 的 conda 环境、常见 Anaconda/Miniconda 路径下的 `semi-utils`、已激活的 `VIRTUAL_ENV`、`qt_gui/.venv`
- 如果找不到可用 Python，会直接失败并提示激活 `conda activate semi-utils` 或设置 `BUILD_PYTHON`
- 安装运行和打包依赖
- 在 Nuitka 构建前验证 PySide6 是否可导入
- 检查 `config.yaml` 是否残留本机绝对路径
- 使用 Nuitka 生成 standalone 版本
- 输出到 `qt_gui/portable/`
- 构建中间产物统一放入 `qt_gui/temp/`，脚本结束时自动删除
- 全量构建日志写入 `qt_gui/build_release.log`
- 发布目录内生成 `run_with_log.bat`，用于捕获 exe 启动失败时的完整运行日志

默认目标是“启动快的便携版 exe”：`portable/SemiUtilsQt/SemiUtilsQt.exe` 是主产物，`SemiUtilsQt-windows.zip` 只是便于分享的压缩包。压缩体积优先级低于 exe 启动速度。

输出位置：

```text
qt_gui/portable/SemiUtilsQt/
qt_gui/portable/SemiUtilsQt/SemiUtilsQt.exe
qt_gui/portable/SemiUtilsQt-windows.zip
```

如果要强制使用某个已有虚拟环境：

```powershell
$env:BUILD_PYTHON = "F:\path\to\conda\envs\semi-utils\python.exe"
.\build_release.bat
```

也可以先激活虚拟环境后再运行：

```powershell
.\.venv\Scripts\Activate.ps1
.\build_release.bat
```

## 1. 打包前清理默认路径

打包前必须把 `qt_gui/config.yaml` 中所有默认资源路径改成相对路径。相对路径会由 `entity/config.py` 按配置文件所在目录解析，因此发布文件夹移动到其他电脑后仍可用。

建议配置规则：

- `base.input_dir` 保持空字符串：`''`
- `base.output_dir` 使用相对目录：`output`
- 字体使用体积更小的 Roboto，避免默认打包 7MB 级字体
- Logo 路径使用 `logos/xxx.png`

示例片段：

```yaml
base:
  font: fonts/Roboto-Regular.ttf
  bold_font: fonts/Roboto-Bold.ttf
  alternative_font: fonts/Roboto-Regular.ttf
  alternative_bold_font: fonts/Roboto-Bold.ttf
  input_dir: ''
  output_dir: output
```

Logo 示例：

```yaml
logo:
  default:
    path: logos/nikon.png
  makes:
    canon:
      id: Canon
      path: logos/canon.png
    nikon:
      id: NIKON
      path: logos/nikon.png
```

检查是否还残留本机绝对路径：

```powershell
rg -n "^[A-Za-z]:|F:/|F:\\|C:/|C:\\" .\config.yaml
```

该命令没有输出才继续打包。

## 2. 准备干净虚拟环境

`qt_gui` 已包含运行所需的 `entity/`、`enums/`、`utils.py`、`init.py` 和 `gen_video.py`，可以作为独立 Python 项目使用。手动构建时，在 `qt_gui` 目录执行：

```powershell
cd F:\A_none_huawei\Photograph\Tools\semi-utils\qt_gui
py -3.10 -m venv .venv-build
.\.venv-build\Scripts\Activate.ps1
python -m pip install --upgrade pip wheel setuptools
pip install -e .
pip install nuitka ordered-set zstandard
```

说明：

- 使用 Python 3.10/3.11 均可，建议和开发环境一致。
- `zstandard` 用于压缩产物，`ordered-set` 是 Nuitka 常用加速依赖。

## 3. 推荐打包命令：Nuitka standalone

在 `qt_gui` 目录执行：

```powershell
python -m nuitka `
  --standalone `
  --enable-plugin=pyside6 `
  --windows-console-mode=force `
  --windows-icon-from-ico=logo.ico `
  --output-dir=build_exe `
  --output-filename=SemiUtilsQt.exe `
  --include-data-file=config.yaml=config.yaml `
  --include-data-file=example.jpg=example.jpg `
  --include-data-file=logo.ico=logo.ico `
  --include-data-dir=logos=logos `
  --include-data-dir=exiftool=exiftool `
  --include-data-file=fonts\Roboto-Regular.ttf=fonts\Roboto-Regular.ttf `
  --include-data-file=fonts\Roboto-Bold.ttf=fonts\Roboto-Bold.ttf `
  --include-data-file=fonts\Roboto-Light.ttf=fonts\Roboto-Light.ttf `
  --include-data-file=fonts\Roboto-Medium.ttf=fonts\Roboto-Medium.ttf `
  --nofollow-import-to=tkinter `
  --nofollow-import-to=matplotlib `
  --nofollow-import-to=numpy `
  main_gui.py
```

产物目录：

```text
build_exe/main_gui.dist/
```

发布前把目录改名：

```powershell
Remove-Item .\portable -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path .\portable | Out-Null
Move-Item .\build_exe\main_gui.dist .\portable\SemiUtilsQt
```

最终分享：

```powershell
Compress-Archive -Path .\portable\SemiUtilsQt -DestinationPath .\portable\SemiUtilsQt-windows.zip -Force
```

## 4. 发布目录必须包含

发布目录中至少需要这些内容：

```text
SemiUtilsQt/
  SemiUtilsQt.exe
  config.yaml
  example.jpg
  logo.ico
  fonts/
    Roboto-Regular.ttf
    Roboto-Bold.ttf
    Roboto-Light.ttf
    Roboto-Medium.ttf
  logos/
  exiftool/
    exiftool.exe
```

`output/` 可以不预先创建。程序首次保存或生成视频时会按相对路径创建。

如果需要视频功能离线可用，可额外放入：

```text
SemiUtilsQt/
  bin/
    ffmpeg.exe
```

否则视频功能会按现有逻辑尝试查找系统 ffmpeg 或下载 ffmpeg。

## 5. 启动速度和体积控制

优先选择：

- 使用 standalone 文件夹发布，不使用单文件模式。
- 只打包 Roboto 字体，不打包 `AlibabaPuHuiTi-*.otf`。
- 不打包 `logs/`、`__pycache__/`、`.idea/`、临时文件。
- 不打包 `qt_gui/temp.txt`。
- 不打包未使用的大型图片或测试输入输出目录。

不建议默认使用 `--onefile`。如果必须得到单个 exe，可改用：

```powershell
python -m nuitka `
  --onefile `
  --enable-plugin=pyside6 `
  --windows-console-mode=force `
  --windows-icon-from-ico=logo.ico `
  --output-dir=build_exe_onefile `
  --output-filename=SemiUtilsQt.exe `
  --include-data-file=config.yaml=config.yaml `
  --include-data-file=example.jpg=example.jpg `
  --include-data-file=logo.ico=logo.ico `
  --include-data-dir=logos=logos `
  --include-data-dir=exiftool=exiftool `
  --include-data-file=fonts\Roboto-Regular.ttf=fonts\Roboto-Regular.ttf `
  --include-data-file=fonts\Roboto-Bold.ttf=fonts\Roboto-Bold.ttf `
  --include-data-file=fonts\Roboto-Light.ttf=fonts\Roboto-Light.ttf `
  --include-data-file=fonts\Roboto-Medium.ttf=fonts\Roboto-Medium.ttf `
  main_gui.py
```

单文件模式更方便复制，但启动时间通常更长，且用户无法直接编辑内置 `config.yaml`。

## 6. 打包后验证

在一台没有项目源码路径的目录中验证，例如：

```powershell
Expand-Archive .\portable\SemiUtilsQt-windows.zip -DestinationPath .\release-test -Force
cd .\release-test\SemiUtilsQt
.\SemiUtilsQt.exe
```

必须检查：

- 首次打开不报找不到 `config.yaml`。
- 如果双击 `SemiUtilsQt.exe` 没有窗口，运行 `run_with_log.bat` 并查看同目录下的 `runtime.log`。
- 输入目录为空。
- 选择图片后预览使用所选图片或目录第一张图片。
- EXIF 能读取，相机厂商和拍摄参数正常显示。
- 输出目录使用发布目录下的 `output/`。
- 关闭程序后再次启动，输入目录仍为空。
- 把整个 `SemiUtilsQt/` 文件夹移动到其他路径后仍能运行。

再次检查发布目录是否残留本机绝对路径：

```powershell
rg -n "^[A-Za-z]:|F:/|F:\\|C:/|C:\\" .\config.yaml
```

没有输出才可以分享。

## 7. 常见问题

如果启动时报 PySide6 插件错误：

- 确认打包命令包含 `--enable-plugin=pyside6`。
- 不要手动删除发布目录中的 Qt 插件目录。

如果 EXIF 为空：

- 确认 `exiftool/exiftool.exe` 在发布目录内。
- 确认杀毒软件没有隔离 `exiftool.exe`。

如果字体或 Logo 找不到：

- 确认 `config.yaml` 使用相对路径。
- 确认对应文件在 `fonts/` 或 `logos/` 目录中。
