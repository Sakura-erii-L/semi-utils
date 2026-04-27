# Semi-Utils LLM 修改指南

本文档用于帮助 LLM 或开发者快速、安全地修改本项目。

## 1. 项目定位

Semi-Utils 是一个照片批处理工具，核心能力有两类：

- 批量处理图片（加水印、边框、阴影、比例填充、背景模糊等）
- 将输出目录图片拼接成视频（可叠加背景音乐）

## 2. 关键入口

- 命令行入口：main.py
- 菜单与处理器实例注册：init.py
- 配置模型：entity/config.py
- 图片容器与 EXIF 读取：entity/image_container.py
- 图片处理器实现：entity/image_processor.py
- 视频生成：gen_video.py
- 工具函数：utils.py

## 3. 配置驱动机制（务必先理解）

配置文件是 config.yaml，运行期由 Config 类加载。

- 运行时对象：init.py 中的 config（全局单例）
- 处理前一般流程：
  1) 读取 config
  2) 根据 config 组装 ProcessorChain
  3) 遍历 input 目录图片
  4) 输出到 output 目录或 input 同目录

关键配置块：

- base：输入输出路径、字体、质量
- layout：布局类型、四角元素、Logo 开关
- global：白边、阴影、等效焦距、按比例填充
- logo：厂商 Logo 映射与默认 Logo

## 4. 处理链规则（修改算法时必看）

当前处理顺序（见 main.py 与 init.py）：

1. 如果启用阴影且布局不是 square，先加 ShadowProcessor
2. 根据布局选择主处理器（watermark/square/simple/background_blur/...）
3. 如果启用白边且布局是 watermark*，最后加 MarginProcessor
4. 如果启用按原图比例填充且布局不是 square，最后加 PaddingToOriginalRatioProcessor

结论：处理器顺序会直接影响最终效果，新增处理器时要明确优先级。

## 5. 常见改动模板

### 5.1 新增布局

1. 在 entity/image_processor.py 新增 ProcessorComponent 子类
2. 在 init.py 的 LAYOUT_ITEMS 里注册
3. 确保配置中的 layout.type 可选值包含新 ID
4. 更新 README 或 GUI 的布局说明

### 5.2 新增四角字段

1. 在 enums/constant.py 增加 NAME 和 VALUE 常量
2. 在 init.py 的 ITEM_LIST 注册
3. 在 entity/image_container.py 的 _param_dict 写入实际值

### 5.3 新增全局开关

1. config.yaml 新增字段
2. entity/config.py 增加 get/set/enable/disable 方法
3. 组装 ProcessorChain 时接入开关判断

## 6. 高风险点（LLM 修改时重点检查）

- config 是全局单例：改动后通常需要 config.save()
- EXIF 读取依赖 exiftool：跨平台路径在 utils.py 中处理
- output_dir 允许为空：为空时输出到 input，并生成新文件名避免覆盖
- 字体路径、Logo 路径都依赖文件存在性
- 视频生成功能依赖 ffmpeg，可能会自动下载

## 7. 建议的最小回归检查

每次改动后至少验证：

1. 能成功读取 input 目录图片（jpg/jpeg/png）
2. 至少一种 watermark 布局处理成功
3. square/simple 布局可正常输出
4. output_dir 为空时不覆盖原图
5. 视频生成功能可执行（有图时）
6. config.yaml 修改后可保存并在下一次运行生效

## 8. 给 LLM 的操作建议

- 优先复用现有 Config、ImageContainer、ProcessorChain，不重复实现核心处理逻辑
- 修改前先确认处理链顺序与配置字段是否一致
- 新增 UI 或接口时，尽量做成“配置输入层”，不要把业务逻辑写死在界面层
- 如果需要跨线程调用，避免直接复用带状态的处理器实例，优先按需新建
