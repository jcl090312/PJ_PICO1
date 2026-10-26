import network
import socket
import time
import json
import gc
from machine import ADC, Pin
from wifi_config import WIFI_SSID, WIFI_PASSWORD

# =========================
# 1. 센서 및 경보 설정
# =========================
sensor = ADC(Pin(26))  # MQ-2 아날로그 출력: GP26

WARNING_LEVEL = 18000
DANGER_LEVEL = 30000

SAMPLE_INTERVAL = 1000  # 1초마다 측정
HISTORY_SIZE = 60       # 최근 60개 측정값
EVENT_SIZE = 30         # 최근 30개 경고 기록

samples = []
events = []

current_raw = 0
current_status = "측정 준비"
current_change = 0
previous_raw = None
previous_status = "정상"
last_sample = time.ticks_ms()
start_ticks = time.ticks_ms()


# =========================
# 2. Wi-Fi 연결
# =========================
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print("Wi-Fi 연결 중...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)

        timeout = 20
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1
            print("연결 대기 중...")

    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        print("Wi-Fi 연결 성공!")
        print("웹사이트 주소: http://" + ip)
        return ip

    raise RuntimeError("Wi-Fi 연결 실패. wifi_config.py를 확인하세요.")


# =========================
# 3. 센서 측정 및 상태 판단
# =========================
def elapsed_seconds():
    return time.ticks_diff(
        time.ticks_ms(), start_ticks
    ) // 1000


def get_status(raw):
    if raw >= DANGER_LEVEL:
        return "위험"
    elif raw >= WARNING_LEVEL:
        return "주의"
    return "정상"


def sample_sensor():
    global current_raw, current_status
    global current_change, previous_raw
    global previous_status, last_sample

    now = time.ticks_ms()

    if time.ticks_diff(now, last_sample) < SAMPLE_INTERVAL:
        return

    last_sample = now

    raw = sensor.read_u16()
    status = get_status(raw)

    if previous_raw is None:
        change = 0
    else:
        change = raw - previous_raw

    current_raw = raw
    current_status = status
    current_change = change

    item = {
        "time": elapsed_seconds(),
        "raw": raw,
        "change": change,
        "status": status
    }

    samples.append(item)

    if len(samples) > HISTORY_SIZE:
        samples.pop(0)

    # 상태가 바뀌어 주의 또는 위험에 진입하면 기록
    if status != previous_status:
        if status in ("주의", "위험"):
            event = {
                "time": elapsed_seconds(),
                "raw": raw,
                "status": status,
                "message": status + " 단계 감지"
            }

            events.append(event)

            if len(events) > EVENT_SIZE:
                events.pop(0)

            print("경고:", status, "측정값:", raw)

    previous_raw = raw
    previous_status = status


# =========================
# 4. 웹사이트에 전달할 데이터
# =========================
def make_data():
    values = [item["raw"] for item in samples]

    if values:
        average = sum(values) / len(values)
        maximum = max(values)
        minimum = min(values)
    else:
        average = 0
        maximum = 0
        minimum = 0

    return {
        "current": {
            "raw": current_raw,
            "voltage": round(current_raw * 3.3 / 65535, 3),
            "percent": round(current_raw * 100 / 65535, 1),
            "change": current_change,
            "status": current_status,
            "time": elapsed_seconds()
        },
        "samples": samples,
        "events": events,
        "stats": {
            "average": round(average, 1),
            "maximum": maximum,
            "minimum": minimum,
            "count": len(values)
        }
    }


# =========================
# 5. CSV 다운로드 데이터
# =========================
def make_csv():
    lines = ["경과시간(초),측정값,변화량,상태"]

    for item in samples:
        lines.append(
            "{},{},{},{}".format(
                item["time"],
                item["raw"],
                item["change"],
                item["status"]
            )
        )

    return "\n".join(lines) + "\n"


# =========================
# 6. 웹 대시보드
# =========================
HTML = r'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>가스 누출 조기 경보 시스템</title>
<style>
* { box-sizing: border-box; }
body {
    margin: 0; padding: 16px;
    font-family: Arial, sans-serif;
    background: #f1f5f9; color: #172033;
}
main { max-width: 1000px; margin: auto; }
h1 { font-size: 26px; }
h2 { font-size: 18px; }
.sub { color: #64748b; font-size: 14px; }
.grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
    gap: 12px; margin: 16px 0;
}
.card {
    background: white; padding: 18px;
    border-radius: 14px;
    box-shadow: 0 2px 8px #0000000a;
}
.label { color: #64748b; font-size: 13px; }
.value { font-size: 27px; font-weight: bold; margin-top: 8px; }
.panel {
    background: white; border-radius: 14px;
    padding: 18px; margin: 14px 0;
}
#banner {
    padding: 17px; border-radius: 12px;
    font-size: 19px; font-weight: bold;
    background: #dcfce7; color: #166534;
}
.normal { background: #dcfce7 !important; color: #166534 !important; }
.warning { background: #fef3c7 !important; color: #92400e !important; }
.danger { background: #fee2e2 !important; color: #991b1b !important; }
button, .download {
    display: inline-block; border: 0; border-radius: 9px;
    padding: 12px 15px; margin: 4px 4px 4px 0;
    background: #1d4ed8; color: white;
    text-decoration: none; font-size: 14px; cursor: pointer;
}
canvas {
    width: 100%; height: 240px;
    display: block;
}
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 10px 6px; border-bottom: 1px solid #e2e8f0; }
.tablewrap { overflow-x: auto; }
.small { font-size: 12px; color: #64748b; }
</style>
</head>
<body>
<main>
<h1>가스 누출 조기 경보 시스템</h1>
<p class="sub">Raspberry Pi Pico W · MQ-2 센서 실시간 모니터링</p>

<div id="banner" class="normal">센서 데이터 연결 중...</div>

<div class="grid">
  <div class="card">
    <div class="label">현재 측정값</div>
    <div class="value" id="raw">-</div>
  </div>
  <div class="card">
    <div class="label">현재 상태</div>
    <div class="value" id="status">-</div>
  </div>
  <div class="card">
    <div class="label">측정값 변화량</div>
    <div class="value" id="change">-</div>
  </div>
  <div class="card">
    <div class="label">ADC 환산 전압</div>
    <div class="value" id="voltage">-</div>
  </div>
</div>

<div class="panel">
  <h2>최근 측정값 그래프</h2>
  <canvas id="chart" width="900" height="260"></canvas>
  <p class="small">
    최근 측정값을 표시합니다. 수직축은 ADC 측정값입니다.
  </p>
</div>

<div class="grid">
  <div class="card">
    <div class="label">평균 측정값</div>
    <div class="value" id="avg">-</div>
  </div>
  <div class="card">
    <div class="label">최댓값</div>
    <div class="value" id="max">-</div>
  </div>
  <div class="card">
    <div class="label">최솟값</div>
    <div class="value" id="min">-</div>
  </div>
  <div class="card">
    <div class="label">누적 측정 개수</div>
    <div class="value" id="count">-</div>
  </div>
</div>

<div class="panel">
  <h2>알림 설정</h2>
  <p class="small">
    브라우저 알림은 지원되는 보안 연결에서만 작동할 수 있습니다.
    알림이 지원되지 않아도 아래 웹 화면 경고는 표시됩니다.
  </p>
  <button onclick="enableNotifications()">브라우저 알림 허용</button>
  <span id="notifyStatus" class="small">알림 설정 확인 전</span>
</div>

<div class="panel">
  <h2>경고 발생 기록</h2>
  <div class="tablewrap">
    <table>
      <thead>
        <tr><th>경과 시간</th><th>측정값</th><th>상태</th><th>내용</th></tr>
      </thead>
      <tbody id="events">
        <tr><td colspan="4">기록을 불러오는 중...</td></tr>
      </tbody>
    </table>
  </div>
  <p class="small">기록은 Pico가 실행되는 동안 메모리에 저장됩니다.</p>
  <a class="download" href="/history.csv">측정 기록 CSV 다운로드</a>
</div>

<div class="panel">
  <h2>측정 기준</h2>
  <p>정상: ADC 값이 주의 기준 미만</p>
  <p>주의: ADC 값이 18000 이상</p>
  <p>위험: ADC 값이 30000 이상</p>
  <p class="small">
    이 기준은 시제품 테스트용 예시이며 실제 가스 농도 기준이 아닙니다.
    인증된 가스 경보기를 대체할 수 없습니다.
  </p>
</div>
</main>

<script>
let previousStatus = null;
let notificationReady = false;
let latestData = null;

async function enableNotifications() {
    if (!("Notification" in window)) {
        document.getElementById("notifyStatus").textContent =
            "이 브라우저는 알림 API를 지원하지 않습니다.";
        return;
    }

    try {
        const permission = await Notification.requestPermission();

        if (permission === "granted") {
            notificationReady = true;
            document.getElementById("notifyStatus").textContent =
                "브라우저 알림 허용됨";
        } else {
            document.getElementById("notifyStatus").textContent =
                "브라우저 알림이 허용되지 않았습니다.";
        }
    } catch (e) {
        document.getElementById("notifyStatus").textContent =
            "이 연결에서는 브라우저 알림을 사용할 수 없습니다.";
    }
}

function showBrowserNotification(status, raw) {
    if (!notificationReady || !("Notification" in window)) return;
    if (Notification.permission !== "granted") return;

    try {
        new Notification("가스 센서 " + status, {
            body: "측정값: " + raw +
                  " / 웹사이트에서 센서 상태를 확인하세요."
        });
    } catch (e) {
        document.getElementById("notifyStatus").textContent =
            "브라우저 알림을 표시할 수 없습니다. 웹 화면 경고를 확인하세요.";
    }
}

function updateBanner(status, raw) {
    const banner = document.getElementById("banner");
    banner.className = status === "위험" ? "danger" :
                       status === "주의" ? "warning" : "normal";

    if (status === "위험") {
        banner.textContent = "위험 단계 감지! 측정값: " + raw;
    } else if (status === "주의") {
        banner.textContent = "주의 단계 감지. 측정값: " + raw;
    } else {
        banner.textContent = "정상 상태 · 측정값: " + raw;
    }
}

function drawChart(data) {
    const canvas = document.getElementById("chart");
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    const pad = 45;

    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = "#e2e8f0";
    ctx.fillStyle = "#64748b";
    ctx.font = "12px Arial";

    const values = data.map(x => x.raw);
    if (values.length === 0) return;

    const maxValue = Math.max(35000, ...values);
    const minValue = 0;

    for (let i = 0; i <= 4; i++) {
        const y = pad + (h - pad * 2) * i / 4;
        ctx.beginPath();
        ctx.moveTo(pad, y);
        ctx.lineTo(w - 10, y);
        ctx.stroke();
        ctx.fillText(
            Math.round(maxValue * (4 - i) / 4),
            3, y + 4
        );
    }

    ctx.strokeStyle = "#2563eb";
    ctx.lineWidth = 2;
    ctx.beginPath();

    values.forEach((v, i) => {
        const x = pad + (w - pad - 15) *
                  (values.length === 1 ? 0 : i / (values.length - 1));
        const y = h - pad - (v / maxValue) * (h - pad * 2);

        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });

    ctx.stroke();

    ctx.fillStyle = "#64748b";
    ctx.fillText("과거", pad, h - 10);
    ctx.fillText("현재", w - 45, h - 10);
}

function updateEvents(events) {
    const tbody = document.getElementById("events");

    if (!events.length) {
        tbody.innerHTML =
            '<tr><td colspan="4">아직 경고 기록이 없습니다.</td></tr>';
        return;
    }

    tbody.innerHTML = events.slice().reverse().map(e =>
        "<tr><td>" + e.time + "초</td>" +
        "<td>" + e.raw + "</td>" +
        "<td>" + e.status + "</td>" +
        "<td>" + e.message + "</td></tr>"
    ).join("");
}

async function update() {
    try {
        const response = await fetch("/data", {cache: "no-store"});
        if (!response.ok) throw new Error("데이터 요청 실패");

        const data = await response.json();
        latestData = data;
        const c = data.current;

        document.getElementById("raw").textContent = c.raw;
        document.getElementById("status").textContent = c.status;
        document.getElementById("change").textContent =
            (c.change > 0 ? "+" : "") + c.change;
        document.getElementById("voltage").textContent =
            c.voltage + " V";

        document.getElementById("avg").textContent = data.stats.average;
        document.getElementById("max").textContent = data.stats.maximum;
        document.getElementById("min").textContent = data.stats.minimum;
        document.getElementById("count").textContent = data.stats.count;

        updateBanner(c.status, c.raw);
        drawChart(data.samples);
        updateEvents(data.events);

        if (previousStatus !== null &&
            c.status !== previousStatus &&
            (c.status === "주의" || c.status === "위험")) {
            showBrowserNotification(c.status, c.raw);
        }

        previousStatus = c.status;
    } catch (e) {
        document.getElementById("banner").className = "warning";
        document.getElementById("banner").textContent =
            "센서 데이터 연결이 끊겼습니다. Pico의 전원과 Wi-Fi를 확인하세요.";
    }
}

update();
setInterval(update, 1000);
</script>
</body>
</html>'''


# =========================
# 7. HTTP 응답 처리
# =========================
def send_response(conn, body, content_type="text/html; charset=utf-8",
                  status="200 OK"):
    if isinstance(body, str):
        body = body.encode("utf-8")

    header = (
        "HTTP/1.1 " + status + "\r\n"
        "Content-Type: " + content_type + "\r\n"
        "Content-Length: " + str(len(body)) + "\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    ).encode("utf-8")

    conn.send(header)

    # 응답을 작은 단위로 보내 메모리 부담 완화
    position = 0
    while position < len(body):
        position += conn.send(body[position:position + 1024])


# =========================
# 8. 프로그램 실행
# =========================
ip = connect_wifi()

server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("0.0.0.0", 80))
server.listen(2)
server.settimeout(0.2)

print("================================")
print("가스 누출 경보 시스템 실행")
print("접속 주소: http://" + ip)
print("종료하려면 Thonny에서 중지 버튼을 누르세요.")
print("================================")

while True:
    sample_sensor()

    try:
        conn, addr = server.accept()
    except OSError:
        continue

    try:
        conn.settimeout(2)
        request = conn.recv(1024)

        if not request:
            continue

        first_line = request.decode("utf-8", "ignore").split("\r\n")[0]
        parts = first_line.split(" ")

        path = parts[1] if len(parts) > 1 else "/"
        path = path.split("?")[0]

        if path == "/data":
            body = json.dumps(make_data())
            send_response(
                conn, body,
                "application/json; charset=utf-8"
            )

        elif path == "/history.csv":
            send_response(
                conn, make_csv(),
                "text/csv; charset=utf-8"
            )

        elif path == "/":
            send_response(conn, HTML)

        else:
            send_response(
                conn, "페이지를 찾을 수 없습니다.",
                "text/plain; charset=utf-8",
                "404 Not Found"
            )

    except Exception as e:
        print("요청 처리 오류:", e)

    finally:
        try:
            conn.close()
        except Exception:
            pass

        gc.collect()
