# IP 代理池过滤工具

从网络上公开的免费代理源抓取代理 IP，过滤出真实有效的代理，按**国内代理池 / 国外代理池**两类保存到本地。

## 功能特性

- **多源抓取**：内置 8 个免费数据源（GitHub 开源列表、开源代理池 API、免费代理网站），自动去重，支持按源启停
- **按协议验证**：HTTP / HTTPS / SOCKS5 分别验证连通性，通过代理访问目标站点确认有效，并记录响应延迟
- **国内外分类**：先用 GeoIP（ip-api.com 免费批量接口）判断 IP 归属国家，再按归属地对应目标站点二次验证：
  - 国内池：中国 IP 且能访问百度
  - 国外池：非中国 IP 且能访问 Google
  - GeoIP 查询失败时自动降级为"按目标站点访问"归类
- **双格式落盘**：txt 每行一个 `ip:port` 便于直接使用；JSON 保存 ip、port、协议、归属地、延迟、来源、验证时间等详细信息
- **全异步并发**：基于 asyncio + aiohttp，验证并发默认 100

## 目录结构

```
├── main.py                   # 程序入口
├── config.py                 # 数据源与参数配置
├── requirements.txt          # 依赖清单
├── proxy_pool/
│   ├── models.py             # Proxy 数据模型与去重
│   ├── sources/              # 数据源抓取器（GitHub 列表 / 开源池 API / 代理网站）
│   ├── validator.py          # 协议验证器（HTTP/HTTPS/SOCKS5）
│   ├── geolocation.py        # GeoIP 归属地批量查询
│   ├── classifier.py         # 国内外分类器
│   └── output.py             # txt + JSON 输出模块
└── data/                     # 运行时生成输出文件
```

## 安装

```bash
# 需要 Python 3.10+
pip install -r requirements.txt
```

## 使用

```bash
# 基础运行（全部数据源）
python main.py

# 指定数据源（逗号分隔源名）
python main.py --sources monosans-http,geonode

# 调整并发与超时
python main.py --concurrency 150 --timeout 5 --max-latency 15

# 跳过 GeoIP（直接按目标站点访问归类）
python main.py --skip-geoip

# 自定义输出目录
python main.py --output-dir my_pool
```

> Windows 控制台中文乱码时，先执行 `chcp 65001` 切换为 UTF-8 编码。

### 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--concurrency` | 代理验证并发数 | 100 |
| `--timeout` | 单个代理验证超时（秒） | 10 |
| `--max-latency` | 延迟上限（秒），超过视为不可用 | 30 |
| `--sources` | 仅启用指定数据源（逗号分隔源名） | 全部 |
| `--output-dir` | 输出目录 | `data` |
| `--skip-geoip` | 跳过 GeoIP 归属地查询 | 关闭 |
| `--quiet` | 仅输出警告与错误 | 关闭 |

## 输出文件

| 文件 | 内容 |
|------|------|
| `data/cn_proxies.txt` | 国内有效代理，每行一个 `ip:port` |
| `data/cn_proxies.json` | 国内代理详细信息（归属地/延迟/来源等） |
| `data/foreign_proxies.txt` | 国外有效代理，每行一个 `ip:port` |
| `data/foreign_proxies.json` | 国外代理详细信息 |

JSON 单条示例：

```json
{
  "ip": "39.106.170.168",
  "port": 8080,
  "protocol": "http",
  "endpoint": "39.106.170.168:8080",
  "country": "CN",
  "region": "Beijing",
  "city": "Beijing",
  "latency": 1.842,
  "source": "monosans-http",
  "verified_at": "2026-08-16T07:57:27+00:00"
}
```

## 数据源说明（config.py 可配置）

| 源名 | 类型 | 默认 | 说明 |
|------|------|------|------|
| monosans-http / monosans-socks5 | GitHub 列表 | 开 | monosans/proxy-list 开源项目，按协议分类清晰 |
| thespeedx-http / thespeedx-socks5 | GitHub 列表 | 开 | TheSpeedX/PROXY-List 开源项目 |
| clarketm-http | GitHub 列表 | 开 | clarketm/proxy-list 开源项目 |
| stormsia-http / stormsia-socks5 | GitHub 列表 | 开 | stormsia/proxy-list 开源项目 |
| geonode | 代理网站 JSON | 开 | proxylist.geonode.com 免费 API（响应较慢） |
| free-proxy-list | 代理网站 HTML | 关 | free-proxy-list.net，部分地区无法直连 |
| go-proxy-pool | 开源池 API | 关 | go_proxy_pool 公开实例不稳定，建议自建后改 `base_url` |
| proxy-pool-api | 开源池 API | 关 | jhao104/proxy_pool 风格 API（默认指向本机 `127.0.0.1:5010`） |

> 开源代理池项目可自建：
> - [pingc0y/go_proxy_pool](https://github.com/pingc0y/go_proxy_pool)：一键部署，内置 14 个免费代理源
> - [jhao104/proxy_pool](https://github.com/jhao104/proxy_pool)：Python + Redis，`python -m proxy_pool` 启动后修改 `config.py` 的 `base_url` 即可接入

## 工作原理

```
抓取(多源) → 去重 → 基础连通性验证(百度) → GeoIP 归属地查询
     → 国外候选二次验证(Google) → 分类 → txt + JSON 落盘
```

- 基础验证：所有候选代理通过代理访问 `https://www.baidu.com`（国内外代理均可访问），记录延迟
- 归属地查询：ip-api.com 免费批量接口（POST /batch，每批 ≤100 IP），超出限频自动退避重试
- 二次验证：国外候选再通过代理访问 `https://www.google.com`，通过者进入国外池
- 降级策略：GeoIP 整体失败时，按"能否访问 Google"区分国内外

## 常见问题

**Q: 验证通过的数量为什么这么少？**
免费代理存活率低是正常现象，有效数量随抓取时间与目标站点波动。可提高 `--concurrency` 加快扫描，或稍后重试。

**Q: 国内代理太少？**
免费公开代理池以国外代理为主，中国 IP 稀缺。可自建 `go_proxy_pool` 获取更多国内数据源后接入。

**Q: 网络环境无法访问 Google？**
国外池的二次验证依赖 Google，若无法访问可用 `--skip-geoip` 或修改 `config.py` 中 `FOREIGN_TARGET_URL` 为可访问站点（如 `https://httpbin.org/ip`）。

**Q: 免费代理安全吗？**
免费代理不可用于敏感操作，请勿传输账号密码等隐私数据。
