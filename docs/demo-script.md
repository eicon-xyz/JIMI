# HAJIMI 演示视频任务脚本

## 可用工具矩阵

| 类别 | 工具 | 说明 |
|------|------|------|
| 桌面应用 | `launch_app` | 系统级启动，L1映射表(60+应用) → L2 PATH查找 → L3 Win+搜索 |
| 桌面操作 | `click` / `double_click` / `type_text` / `press_key` / `scroll` / `wait` | 基于OmniParser元素检测的精确操作 |
| 浏览器 | `browser_navigate` / `browser_snapshot` / `browser_click` / `browser_type` / `browser_scroll` / `browser_screenshot` / `browser_close` | Playwright/CDP DOM级精确控制 |
| 意向识别 | 内置管线 | 9类意图分类(SetFit+关键词) + 红线安全检查(23条) + L2/L3复杂度路由 |
| 自动记忆 | 内置管线 | 3层记忆(用户画像/成功模式/失败教训) + embedding检索 + 去重合并 |

## 配置参数

| 参数 | 值 |
|------|-----|
| MAX_TOOL_CALL_ROUNDS | 50 |
| STEP_RETRY_LIMIT | 3 |

---

## 任务一：桌面应用操作 —— AI辅助内容创作

**演示能力**：应用启动 + 文本输入 + 键盘快捷键 + 文件保存（多桌面应用协同）

**用户指令**：
> 打开记事本，写一篇500字关于人工智能的短文，标题为"AI改变生活"，写完保存到桌面

**预期步骤**：
1. launch_app("记事本")
2. type_text(输入框, 短文内容)
3. press_key("ctrl+s")
4. type_text(文件名输入框, "AI改变生活.txt")
5. 点击保存到桌面路径
6. mark_step_done

**录制要点**：
- 展示记事本自动打开并开始输入
- 展示中文输入能力
- 展示Ctrl+S快捷键自动触发保存对话框
- 最终桌面出现文件

**展示能力点**：应用启动映射表、中文文本输入、键盘快捷键、多步协同

---

## 任务二：浏览器自动化 —— 信息采集与整理

**演示能力**：浏览器DOM操作 + 网页信息提取 + 多页面浏览

**用户指令**：
> 打开浏览器访问 GitHub Trending Python 页面（github.com/trending/python?since=daily），浏览前三个项目，记录每个项目的名称、Star数、简介

**预期步骤**：
1. browser_navigate("https://github.com/trending/python?since=daily")
2. browser_snapshot() → 获取页面结构
3. browser_click(第一个项目链接) → 进入详情页
4. browser_snapshot() → 提取Star数、简介
5. browser_navigate("https://github.com/trending/python?since=daily") → 返回列表
6. 重复步骤3-5处理第二、第三个项目
7. launch_app("记事本") → 打开记事本记录
8. type_text(输入框, 整理好的Markdown表格)
9. press_key("ctrl+s") → 保存

**录制要点**：
- 展示浏览器自动启动并导航
- 展示DOM快照和元素点击
- 展示跨页面信息提取
- 最终打开记事本写入整理好的数据

**展示能力点**：浏览器DOM操作、页面导航、结构化信息提取、跨应用数据流转

---

## 任务三：失败场景 —— DNS解析失败

**演示能力**：安全红线拦截 + 优雅拒绝 + 意图分类

**用户指令**：
> 我刚刚写了一篇500字的文章，能帮我重写成长点的版本吗

**预期流程**：
1. 红线检查通过（无危险操作）
2. 意图分类 → content_cognition（内容认知）
3. 规划生成：打开记事本 → 查找文件 → 读取内容 → 重写
4. 执行过程中——文件不存在/路径错误
5. agent自动重试（最多3次）
6. 最终标记失败 → 触发failure_lesson记忆提取

**录制要点**：
- 展示agent尝试打开文件但失败
- 展示重试机制（自动切换策略）
- 展示失败的failure_lesson存入数据库
- 展示优雅的错误处理

---

## 任务四：记忆系统展示

**演示能力**：3层自动记忆系统

### 4A — 记忆检索注入

1. 先执行任务一："打开记事本写短文"（记忆系统自动提取：`记事本`、`剪贴板输入中文`、`Ctrl+S保存到桌面`）
2. 再执行："帮我写篇日记保存"
3. **对比展示**：第二次任务的Planner prompt中自动注入了`[相关记忆] 该用户习惯用记事本，用Ctrl+S保存到桌面`

### 4B — 去重合并

1. 连续执行5次"打开浏览器搜索Python项目"
2. 展示数据库：`t_memories`表中只有**1条**`success_pattern`（category=`task_workflow`），其余4条`is_active=False`

### 4C — 失败教训消解

1. 先触发一次失败（如打开不存在的路径保存文件）
2. 数据库出现`failure_lesson`
3. 再次成功完成同类任务
4. 数据库：失败教训自动标记`is_active=False`（`resolved_count=1`）

### 数据库展示

录制最后切换到DB视图，展示：

```
sqlite> SELECT memory_type, category, is_active, summary FROM t_memories;

success_pattern | task_workflow | 1 | [记事本] 写短文并Ctrl+S保存到桌面
success_pattern | task_workflow | 0 | [记事本] 写短文并保存    ← 已被覆盖
failure_lesson  | failure_avoidance | 0 | 无法找到文件路径    ← 已被消解
success_pattern | task_workflow | 1 | [记事本] 写日记保存到桌面
success_pattern | task_workflow | 1 | [Chrome] 浏览GitHub Trending提取项目信息
```

**录制要点**：
- 冷启动任务 → 有记忆任务，展示prompt中的`[相关记忆]`块
- 展示数据库`t_memories`表的内容变化
- 用SQL查询对比`is_active=1` vs `is_active=0`

**展示能力点**：全自动学习、语义相似度检索、去重合并、失败消解

---

## 录制建议

| 场景 | 时长 | 录制重点 |
|------|------|---------|
| 任务一 | 60s | 记事本自动输入、Ctrl+S保存、文件出现在桌面 |
| 任务二 | 90s | 浏览器启动、GitHub页面导航、信息提取 |
| 任务三 | 60s | 失败重试、优雅降级、错误处理 |
| 任务四 | 90s | 记忆注入对比、数据库展示、去重和消解 |
| 总计 | 5min | — |

### 屏幕录制设置

- 分辨率: 1920×1080
- 同时录制: HAJIMI B端界面 + Windows桌面 + 终端(DB查询)
- 终端窗口放在右侧展示实时日志
- DB查询用独立窗口，切换过去展示数据结构
