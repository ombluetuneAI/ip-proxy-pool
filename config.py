"""集中配置：数据源清单、验证参数、GeoIP 接口、输出目录。"""

# ==================== 数据源配置 ====================
# 每个源: (name, enabled, type, url/payload)
#   type: "github_list"   GitHub 原始文本列表，每行 ip:port
#         "open_source"   开源代理池 JSON API
#         "website"       免费代理网站（HTML 表格或 JSON API）

SOURCES = [
    # ---- GitHub 原始列表 ----
    {
        "name": "monosans-http",
        "enabled": True,
        "type": "github_list",
        "url": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        "protocol": "http",
    },
    {
        "name": "monosans-socks5",
        "enabled": True,
        "type": "github_list",
        "url": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
        "protocol": "socks5",
    },
    {
        "name": "thespeedx-http",
        "enabled": True,
        "type": "github_list",
        "url": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "protocol": "http",
    },
    {
        "name": "thespeedx-socks5",
        "enabled": True,
        "type": "github_list",
        "url": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
        "protocol": "socks5",
    },
    {
        "name": "clarketm-http",
        "enabled": True,
        "type": "github_list",
        "url": "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
        "protocol": "http",
    },
    {
        "name": "stormsia-http",
        "enabled": True,
        "type": "github_list",
        "url": "https://raw.githubusercontent.com/stormsia/proxy-list/main/http.txt",
        "protocol": "http",
    },
    {
        "name": "stormsia-socks5",
        "enabled": True,
        "type": "github_list",
        "url": "https://raw.githubusercontent.com/stormsia/proxy-list/main/socks5.txt",
        "protocol": "socks5",
    },

    # ---- 开源代理池公开 API ----
    # go_proxy_pool 风格: GET {base}/api/proxy 返回 {"data": [{"ip":..., "port":..., "type":"http"}]}
    # 公开实例不稳定，建议自建后修改 base_url 使用
    {
        "name": "go-proxy-pool",
        "enabled": False,
        "type": "open_source",
        "base_url": "http://pool.proxy.ip:8899",
        "endpoint": "/api/proxy",
        "response_path": "data",
    },
    # jhao104/proxy_pool 风格: GET {base}/all/ 返回 {"proxy": [...]}
    {
        "name": "proxy-pool-api",
        "enabled": False,
        "type": "open_source",
        "base_url": "http://127.0.0.1:5010",
        "endpoint": "/all/",
        "response_path": "proxy",
    },

    # ---- 免费代理网站 ----
    {
        "name": "free-proxy-list",
        "enabled": False,
        "type": "website",
        "url": "https://free-proxy-list.net/",
        "kind": "html_table",
    },
    {
        "name": "geonode",
        "enabled": True,
        "type": "website",
        "url": "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc",
        "kind": "json_api",
    },
]

# ==================== 请求参数 ====================
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 抓取阶段
FETCH_TIMEOUT = 60           # 单个源抓取超时（秒，geonode 响应较慢需要 60s）
FETCH_RETRIES = 2            # 抓取失败重试次数

# 验证阶段
VERIFY_CONCURRENCY = 100     # 并发验证的代理数量上限
VERIFY_TIMEOUT = 5           # 单个代理验证超时（秒）
MAX_LATENCY = 5.0            # 延迟上限（秒），超过视为不可用

# ==================== 验证目标站点 ====================
# 国内目标：用于验证国内候选代理
CN_TARGET_URL = "https://www.baidu.com"
# 国外目标：用于验证国外候选代理
FOREIGN_TARGET_URL = "https://www.google.com"
# 辅助目标：httpbin.org/ip 返回出口 IP，可同时用于匿名度参考（非必需）
ASSIST_TARGET_URL = "https://httpbin.org/ip"

# ==================== GeoIP 配置 ====================
# 离线数据库优先：若文件存在则本地查（零网络、零限频），否则回退在线 ip-api
GEOIP_MMDB_PATH = "geolite2-country.mmdb"
GEOIP_BATCH_URL = "http://ip-api.com/batch"
GEOIP_MAX_BATCH = 100        # 每次批量查询的 IP 数上限（免费接口限制）
GEOIP_RATE_SLEEP = 1.0       # 批量请求间隔（秒），规避 45 次/分钟限频
GEOIP_MAX_RETRIES = 3        # 批量请求重试次数

# ==================== 输出配置 ====================
OUTPUT_DIR = "data"
CN_PREFIX = "cn_proxies"             # 国内代理池文件名前缀
FOREIGN_PREFIX = "foreign_proxies"   # 国外代理池文件名前缀
