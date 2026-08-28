# Hướng dẫn sử dụng

Tài liệu này đi theo thứ tự bạn thật sự sẽ làm, từ máy trắng đến bài đăng đầu tiên.
Phần giải thích *vì sao* nằm ở [README.md](README.md).

Mọi lệnh dưới đây viết cho PowerShell trên Windows, chạy từ thư mục `Ads`.

---

## 1. Cài đặt (làm một lần)

Khởi động Postgres và Redis:

```bash
docker compose up -d
```

Tạo môi trường Python và cài phụ thuộc:

```bash
python -m venv .venv; .\.venv\Scripts\pip install -e ".[dev]"
```

Tạo file cấu hình, khoá mã hoá và token đăng nhập:

```bash
Copy-Item .env.example .env; .\.venv\Scripts\python scripts/gen_vault_key.py >> .env; .\.venv\Scripts\python scripts/gen_api_token.py >> .env
```

> **Sao lưu `VAULT_KEY` ngay.** Nó mã hoá toàn bộ cookie jar. Mất khoá là mất hết
> phiên đăng nhập, không có đường khôi phục. Cất riêng, đừng để chung với bản sao lưu
> database.

`API_TOKEN` là thứ bạn dán vào dashboard lúc mở lần đầu. Chưa đặt thì API **từ chối mọi
request** — cố ý như vậy, vì một hệ thống giữ cookie jar của hàng chục tài khoản mà
"tạm để mở" là cách mất sạch.

Tải trình duyệt Camoufox (khoảng 150 MB) rồi tạo bảng:

```bash
.\.venv\Scripts\python -m camoufox fetch; .\.venv\Scripts\python scripts/init_db.py
```

`init_db.py` chạy Alembic bên dưới nên dùng được cả cho DB trống lẫn DB đã có dữ liệu.
Sau này đổi schema thì `alembic revision --autogenerate -m "mô tả"` rồi chạy lại lệnh
trên — không phải xoá database nữa.

Kiểm tra mọi thứ chạy được:

```bash
.\.venv\Scripts\python scripts/demo_seed.py
```

---

## 2. Chạy hệ thống

Cài phụ thuộc cho dashboard (làm một lần):

```bash
cd web; npm install; Copy-Item .env.local.example .env.local; cd ..
```

Cần **ba cửa sổ terminal** chạy song song.

Cửa sổ 1 — API:

```bash
.\.venv\Scripts\uvicorn seeding.api.main:app --reload
```

Cửa sổ 2 — worker (thứ thật sự đăng bài):

```bash
.\.venv\Scripts\arq seeding.worker.settings.WorkerSettings
```

Cửa sổ 3 — dashboard:

```bash
npm run dev --prefix web
```

Rồi mở **`http://127.0.0.1:3000`**. Lần đầu nó hỏi token — dán giá trị `API_TOKEN` từ
`.env` vào. Token được lưu trong trình duyệt đó, không gửi đi đâu khác. Đổi token thì
mọi trình duyệt đang mở phải nhập lại.

Giao diện bằng **tiếng Anh**. Bảy màn hình:

| Màn hình | Đường dẫn | Dùng để |
|---|---|---|
| **Overview** | `/` | Việc cần làm trước, số liệu sau. Có tài khoản chờ người thì nó nằm trên cùng. |
| **Compose** | `/compose` | Gõ template, chèn hashtag, gắn media, thấy ngay bài từng tài khoản sẽ đăng và **cảnh báo nguy cơ trùng**. |
| **Media** | `/media` | Kéo-thả ảnh/video vào, xem trước, xoá. File đang được dùng thì không xoá nhầm được. |
| **Hashtags** | `/hashtags` | Túi hashtag để rút ngẫu nhiên. Tạo, sửa, xoá. |
| **Schedule** | `/schedule` | Ba cột **Campaigns → Groups → Posts** kiểu Ads Manager. Bấm dọc theo hàng để lọc dần. |
| **Accounts** | `/accounts` | Ba tab: tài khoản, profile, proxy. Sửa/xoá tại chỗ, **test proxy** từng cái hoặc **test all**. |
| **Takeovers** | `/takeovers` | Tài khoản đang kẹt, lý do, **mã 2FA tự làm mới**, và nút chốt. |

`http://127.0.0.1:8000/docs` vẫn còn — đó là Swagger cho toàn bộ API, hữu ích khi bạn
muốn tự động hoá hoặc gọi những thứ dashboard chưa có.

> **Giao diện không mở được trình duyệt trên máy bạn.** Trang web không có quyền đó. Vì
> vậy những thao tác cần trình duyệt thật — đăng nhập lần đầu, giải checkpoint — được
> hiện dưới dạng lệnh kèm nút chép, bạn dán vào terminal.

> API bắt buộc token trên mọi route trừ `/health`. Nhưng đây vẫn là **một token dùng
> chung, không phải hệ thống người dùng** — chỉ chạy trên localhost, đừng mở ra Internet.

---

## 3. Luồng A — Reddit (làm cái này trước)

Reddit đi bằng API chính thức nên không cần trình duyệt, không cần proxy, không sợ
checkpoint. Làm nó trước để chạy thông toàn bộ pipeline trước khi đụng phần khó.

### 3.1. Lấy khoá API cho tài khoản

Đăng nhập bằng chính tài khoản seeding đó, vào `reddit.com/prefs/apps`, tạo app loại
**script**. Ghi lại `client_id` (chuỗi ngắn dưới tên app) và `client_secret`.

Sửa `REDDIT_USER_AGENT` trong `.env` cho đúng — Reddit yêu cầu chuỗi mô tả rõ ràng:

```
REDDIT_USER_AGENT=ten-du-an/0.1 by u/tai_khoan_chinh_cua_ban
```

### 3.2. Tạo workspace, persona, tài khoản

> **Nhanh hơn:** mở màn hình **Accounts** trên dashboard rồi bấm *Add account*.
> Form đó tự tạo workspace và persona nếu chưa có. Phần lệnh dưới đây để bạn tự động
> hoá khi cần thêm hàng loạt.

```powershell
$api = "http://127.0.0.1:8000"
# Doc token tu .env de khong phai dan tay vao tung lenh
$token = (Select-String -Path .env -Pattern '^API_TOKEN=(.+)$').Matches[0].Groups[1].Value
$H = @{ Authorization = "Bearer $token" }

$ws = Invoke-RestMethod -Headers $H -Method Post -Uri "$api/workspaces" -ContentType 'application/json' `
  -Body (@{ name = 'Cong ty A' } | ConvertTo-Json)

$persona = Invoke-RestMethod -Headers $H -Method Post -Uri "$api/personas" -ContentType 'application/json' `
  -Body (@{ workspace_id = $ws.id; name = 'Hai Yen'; interests = @('cong nghe') } | ConvertTo-Json)

$acc = Invoke-RestMethod -Headers $H -Method Post -Uri "$api/accounts" -ContentType 'application/json' `
  -Body (@{
    persona_id = $persona.id
    platform   = 'reddit'
    handle     = 'ten_acc_reddit'
    daily_cap  = 3
    secrets    = @{
      client_id     = 'CLIENT_ID'
      client_secret = 'CLIENT_SECRET'
      username      = 'ten_acc_reddit'
      password      = 'MAT_KHAU'
    }
  } | ConvertTo-Json -Depth 5)
```

> **Bẫy PowerShell:** `ConvertTo-Json` mặc định chỉ đi sâu 2 tầng. Payload nào có object
> lồng nhau (`secrets`, `groups`) **phải** thêm `-Depth 5`, không thì trường lồng bị
> biến thành chuỗi vô nghĩa và API trả 422.

`secrets` được mã hoá ngay khi ghi xuống database và không bao giờ đọc ngược ra qua API.

`daily_cap` là trần **sau khi warm-up xong**. Tài khoản mới bắt đầu ở 1 bài/ngày và tăng
dần qua `WARMUP_DAYS` (mặc định 14 ngày).

### 3.3. Soạn nội dung

`title_template` và `body_template` dùng cú pháp spintax `{a|b|c}`, lồng nhau được. Mỗi
tài khoản sẽ nhận một tổ hợp khác nhau:

```powershell
$content = Invoke-RestMethod -Headers $H -Method Post -Uri "$api/content" -ContentType 'application/json' `
  -Body (@{
    workspace_id   = $ws.id
    title_template = '{Vua thu|Moi test|Nghich thu} mot cong cu {lap lich|dang bai}'
    body_template  = '{Minh|To} {dung|xai} duoc {vai hom|mot tuan} roi, {thay on|tam on}.'
  } | ConvertTo-Json)

Invoke-RestMethod -Headers $H -Method Post -Uri "$api/content/$($content.id)/approve"
```

Bài chưa duyệt thì không lập lịch được — đó là chốt chặn cố ý.

**Càng nhiều lựa chọn càng tốt.** Template trên có 3×2 tiêu đề × 2×2×2×2 thân bài = 288
tổ hợp. Với 5 tài khoản thì xác suất trùng khoảng 3%. Với 50 tài khoản thì gần như chắc
chắn trùng — lúc đó phải thêm nhánh.

### 3.4. Tạo chiến dịch và lập lịch

> **Nhanh hơn:** màn hình **Schedule** có nút *New campaign* — chọn nội dung đã duyệt,
> bấm chọn tài khoản, kéo thanh cửa sổ rải, xong là nó lập lịch luôn. Nó còn cảnh báo
> khi cửa sổ quá hẹp so với số tài khoản.

```powershell
$campaign = Invoke-RestMethod -Headers $H -Method Post -Uri "$api/campaigns" -ContentType 'application/json' `
  -Body (@{
    workspace_id           = $ws.id
    content_item_id        = $content.id
    name                   = 'Chien dich dau tien'
    stagger_window_seconds = 3600
    groups = @(
      @{
        name        = 'Nhom r/test'
        platform    = 'reddit'
        target      = @{ subreddit = 'test' }
        account_ids = @($acc.id)
      }
    )
  } | ConvertTo-Json -Depth 6)

$jobs = Invoke-RestMethod -Headers $H -Method Post -Uri "$api/campaigns/$($campaign.id)/plan"
$jobs | Format-Table handle, scheduled_at, status, title
```

`stagger_window_seconds` là cửa sổ rải bài. Mỗi tài khoản được ném vào một mốc ngẫu
nhiên trong cửa sổ đó. **Đừng đặt 0** — mười tài khoản đăng trong cùng một giây là mẫu
hình dễ phát hiện nhất.

Gọi `/plan` lại bao nhiêu lần cũng được, không sinh job trùng.

### 3.5. Chờ worker chạy

Worker quét mỗi 30 giây. Xem kết quả:

```powershell
Invoke-RestMethod -Headers $H -Uri "$api/campaigns/$($campaign.id)/jobs" |
  Format-Table handle, status, scheduled_at, remote_url, last_error
```

Trạng thái job: `scheduled` → `running` → `succeeded` / `failed` / `needs_human`.

Nếu thấy `failed` kèm `rate governor`, đó **không phải lỗi** — tài khoản đã chạm trần
ngày hôm đó, job tự lùi lại một tiếng.

Thử trên `r/test` trước khi đụng vào sub thật.

### 3.6. Bình luận thay vì đăng bài, và chiến dịch lặp lại

Khi tạo chiến dịch, ô **What are these accounts doing?** chọn một trong hai:

- **Posting to their own profile** — như từ trước tới giờ. Reddit cần tên subreddit.
- **Commenting on someone else's post** — dán URL bài cần vào. Mọi nền tảng dùng chung
  một ô `url` này.

Seeding ngoài đời phần lớn là bình luận: một tài khoản mới lập mà tuần nào cũng đăng bài
quảng cáo là mẫu hình dễ thấy, còn một tài khoản để lại bình luận dưới bài người khác thì
lẫn vào đám đông.

Bình luận chỉ lấy phần **body** của nội dung — tiêu đề không có chỗ nào để đi trong một
bình luận. Nội dung chỉ có tiêu đề sẽ bị từ chối kèm lý do, chứ không lặng lẽ đăng thiếu.

Ô **Repeat** đặt `Every day` hoặc `Every week` thì mỗi kỳ hệ thống sinh một **bản sao
mới** của chiến dịch, cùng nội dung và cùng nhóm tài khoản, nhưng biến thể khác nhau —
đăng y hệt một câu mỗi tuần là dấu vết rõ hơn cả việc đăng cùng giờ.

Trên màn hình Schedule, chiến dịch lặp lại có nhãn `daily`/`weekly` và dòng cho biết kỳ
kế tiếp rơi vào lúc nào, kèm nút *spawn the next one now* để thử trước khi giao cho lịch.
Bản sao mang nhãn `copy`.

Nếu worker chết vài ngày, **các kỳ bị lỡ sẽ bị bỏ chứ không bù**. Bù đủ bảy kỳ sau một
tuần chết là bảy chiến dịch cùng đến hạn một lúc — toàn bộ tài khoản đăng liên tục trong
vài phút, đúng thứ cần tránh nhất.


---

## 4. Luồng B — Threads, X, Facebook, Instagram, TikTok

Những nền tảng này không có đường API cho tài khoản cá nhân, nên phải đi bằng trình
duyệt. Thêm ba bước so với Reddit: proxy, profile, và đăng nhập tay.

### 4.1. Thêm proxy

Một tài khoản một proxy, **gắn cứng, không xoay**. Dùng proxy dân cư sticky, không dùng
datacenter, không dùng rotating.

```powershell
$proxy = Invoke-RestMethod -Headers $H -Method Post -Uri "$api/proxies" -ContentType 'application/json' `
  -Body (@{
    label    = 'vn-residential-01'
    host     = '1.2.3.4'
    port     = 8080
    username = 'user'
    password = 'pass'
    kind     = 'residential'
    region   = 'VN'
  } | ConvertTo-Json)
```

### 4.2. Tạo tài khoản và profile

```powershell
$acc2 = Invoke-RestMethod -Headers $H -Method Post -Uri "$api/accounts" -ContentType 'application/json' `
  -Body (@{
    persona_id = $persona.id
    platform   = 'threads'
    handle     = 'ten_acc_threads'
    secrets    = @{ password = 'MAT_KHAU'; totp_seed = 'SEED_2FA_BASE32' }
  } | ConvertTo-Json -Depth 5)

$prof = Invoke-RestMethod -Headers $H -Method Post -Uri "$api/profiles" -ContentType 'application/json' `
  -Body (@{ account_id = $acc2.id; proxy_id = $proxy.id } | ConvertTo-Json)

$prof.fingerprint
```

`totp_seed` là chuỗi base32 hiện ra lúc bật 2FA (chỗ "không quét được mã QR? nhập tay").
Lưu nó vào đây thì script sẽ tự in mã 2FA cho bạn mỗi lần cần.

Profile **chỉ tạo được một lần**. Gọi lại trả về 409 — cố ý, vì tạo lại sẽ sinh
fingerprint mới, đúng thứ bất thường mà hệ thống này có để tránh.

### 4.3. Đăng nhập tay (bước quan trọng nhất)

```bash
.\.venv\Scripts\python scripts/login_profile.py threads ten_acc_threads
```

Script mở Camoufox với đúng fingerprint và proxy của profile đó. Bạn đăng nhập bằng tay
trong cửa sổ vừa mở — kể cả 2FA và captcha — rồi quay lại terminal ấn Enter. Cookie jar
được mã hoá và lưu vào profile.

**Làm một lần rồi thôi.** Khi phiên chết, chạy lại đúng lệnh này. Đừng viết code tự đăng
nhập lại — đó là cách nhanh nhất để mất tài khoản.

### 4.4. Bật hoạt động nền

Một tài khoản chỉ đăng bài rồi biến mất là mẫu bot rõ nhất. Lập lịch cuộn feed, đọc bài,
xem video:

```powershell
Invoke-RestMethod -Headers $H -Method Post -Uri "$api/activity/plan"
```

Worker tự chạy lệnh này lúc 6h sáng mỗi ngày. Mỗi bài đăng đi kèm khoảng 6 lần "sống"
không đăng gì, rải đều trong khung 7h–23h.

Xem lịch của một tài khoản:

```powershell
Invoke-RestMethod -Headers $H -Uri "$api/accounts/$($acc2.id)/activity" |
  Format-Table kind, scheduled_at, status, detail
```

### 4.5. Chiến dịch thì giống hệt Reddit

Chỉ đổi `platform` thành `threads` (hoặc `x`, `facebook`, `instagram`, `tiktok`) và bỏ
`target.subreddit` đi.

> **Selector chưa kiểm chứng.** Các nền tảng này đổi giao diện liên tục và tôi không có
> tài khoản thật để xác minh. Bài đầu tiên nhiều khả năng báo lỗi kiểu *"Khong tim thay
> o soan noi dung. Da thu: [...]"* — lúc đó mở
> [adapters/browser.py](src/seeding/adapters/browser.py), tìm `RECIPES`, sửa selector
> cho đúng. Toàn bộ selector gom một chỗ đúng để dễ sửa.

---

## 5. Bài có ảnh hoặc video

Đặt file gốc vào `media/sources/`, rồi khai `media_ref` khi tạo nội dung:

```powershell
$content = Invoke-RestMethod -Headers $H -Method Post -Uri "$api/content" -ContentType 'application/json' `
  -Body (@{
    workspace_id   = $ws.id
    title_template = '{Chia se|Gui moi nguoi} mot clip {hay|thu vi}'
    media_ref      = 'clip-goc.mp4'
  } | ConvertTo-Json)
```

Mỗi tài khoản sẽ nhận một bản render riêng — cắt viền, đổi tốc độ, chỉnh sáng, thêm
nhiễu, xoá metadata. Render chạy ngay trước khi đăng và có cache, nên chạy lại không tốn
thêm gì.

Chọn mức biến đổi trong `.env`:

```
MEDIA_STRENGTH=moderate
```

Xem con số thật để tự quyết:

```bash
.\.venv\Scripts\python scripts/demo_media.py
```

| Mức | Hash file | pHash giữa các bản | Nghĩa là |
|---|---|---|---|
| `subtle` | khác | **0** | Bộ so khớp tri giác vẫn coi cả 5 bản là **một file** |
| `moderate` | khác | 2–16 | Bắt đầu là nội dung khác nhau |
| `aggressive` | khác | 4–34 | Khác rõ, nhưng nhìn ra được |

Nếu nền tảng so khớp tri giác tốt thì không mức nào cứu được — câu trả lời thật là quay
hoặc dựng **nội dung gốc khác nhau** cho từng nhóm tài khoản.

Instagram và TikTok **bắt buộc** có media; đăng bài chỉ có chữ sẽ bị từ chối ngay với
thông báo rõ ràng.

---

## 6. Vận hành hằng ngày

### 6.0. Nhập tài khoản hàng loạt

Nhập tay từng cái là việc ổn với mười tài khoản và không chịu nổi với một trăm. Màn hình
**Accounts → Import CSV** nhận file có cột:

```
platform,handle,persona,daily_cap,start_warmup,client_id,client_secret,username,password,totp_seed,recovery_email
reddit,seed_reddit_01,Sinh vien HN,3,yes,abc123,secret456,seed_reddit_01,hunter2,,
facebook,seed.fb.01,Sinh vien HN,2,yes,,,,hunter2,JBSWY3DPEHPK3PXP,backup@example.com
```

Bắt buộc: `platform`, `handle`. Còn lại tuỳ chọn. Nút *download a template* cho sẵn file
mẫu. Persona chưa có sẽ được tạo tự động theo tên trong file.

Nhấn chọn file thì hệ thống **kiểm trước, chưa tạo gì**: bạn thấy danh sách dòng hợp lệ
và toàn bộ dòng hỏng kèm số dòng khớp với Excel. Có một dòng hỏng là mặc định không nhập
gì cả — hoặc bấm *Import the good rows* để bỏ qua phần hỏng.

> **Xoá file CSV sau khi nhập xong.** Nó chứa mật khẩu ở dạng chữ thường. Giá trị được
> mã hoá trên đường vào database, còn file trên ổ đĩa bạn thì không.

Tài khoản nhập xong vẫn cần **profile** và **đăng nhập tay lần đầu** như mục 4.2–4.3.

### 6.1. Xem có tài khoản nào cần bạn không

Buổi sáng, xem có tài khoản nào cần bạn không:

```bash
.\.venv\Scripts\python scripts/takeover.py list
```

Có thì mở ra giải:

```bash
.\.venv\Scripts\python scripts/takeover.py open threads ten_acc_threads
```

Trình duyệt mở ra đúng phiên đó, in sẵn mã 2FA. Giải captcha hoặc nhập mã xác minh xong,
ấn Enter — cookie mới được lưu lại. Rồi chốt:

```bash
.\.venv\Scripts\python scripts/takeover.py resolve threads ten_acc_threads "da nhap ma xac minh"
```

Tài khoản quay về `WARMING` chứ không phải `ACTIVE` — vừa qua checkpoint thì đi chậm lại
một nhịp. Job bị kẹt được hẹn lại sau 6 tiếng, không chạy ngay.

Tài khoản không cứu được nữa:

```bash
.\.venv\Scripts\python scripts/takeover.py abandon threads ten_acc_threads "bi khoa han"
```

Xem sức khoẻ toàn bộ profile:

```powershell
Invoke-RestMethod -Headers $H -Uri "$api/profiles" |
  Format-Table handle, platform, session_alive, last_health_at, consecutive_health_failures
```

Xem nhật ký vòng đời của một profile — đây là thứ đầu tiên cần nhìn khi một nhóm tài
khoản chết cùng lúc:

```powershell
Invoke-RestMethod -Headers $H -Uri "$api/profiles/$($prof.id)/events" | Format-Table created_at, kind, detail
```

### 6.2. Được báo thay vì phải nhớ mở dashboard

Acc kẹt lúc 2 giờ sáng thì nó nằm im tới khi bạn mở dashboard. Đặt trong `.env`:

```
ALERT_KIND=telegram
ALERT_WEBHOOK_URL=https://api.telegram.org/bot<TOKEN>/sendMessage
ALERT_TELEGRAM_CHAT_ID=123456789
```

`ALERT_KIND` nhận `telegram`, `discord`, `slack`, hoặc `generic`. Discord và Slack chỉ
cần URL webhook, không cần chat id. Khởi động lại API và worker sau khi sửa.

Mỗi tài khoản kẹt chỉ báo **một lần** — báo lại mỗi vòng quét là cách nhanh nhất để bạn
tắt thông báo đi rồi bỏ lỡ lần thật sự quan trọng. Tin nhắn chỉ mang tên tài khoản, nền
tảng và lý do; **không bao giờ có mật khẩu, mã 2FA hay cookie**.

### 6.3. Đặt khung giờ thức cho từng nền tảng

Màn hình **Hours**. Nền tảng nào không đặt riêng thì chạy 7h–23h theo giờ máy chủ.

Giờ cao điểm của TikTok và Facebook khác hẳn nhau, và một tài khoản hoạt động lệch hẳn
với nhịp của nền tảng đó là một dấu vết. Khung này chi phối **hoạt động nền** (cuộn feed,
đọc bài, thả cảm xúc) — giờ đăng bài đến từ cửa sổ rải của từng chiến dịch.

Khung vắt qua nửa đêm không được hỗ trợ. Giờ thức trải qua 3h sáng chính là mẫu hình mà
tính năng này sinh ra để tránh.

### 6.4. Đọc bảng sống sót

Màn hình **Survival**, cắt theo loại proxy, nhà cung cấp, độ dài warm-up và nhịp đăng.

Đặt tên proxy theo nhà cung cấp (`Provider A - VN 01`) thì bảng "By proxy provider" mới
có ích. Hàng nào dưới 12 tài khoản bị làm mờ: với 8 tài khoản một nhóm thì chênh lệch
60% và 75% là nhiễu, không phải phát hiện.

Đây cũng không phải thí nghiệm có đối chứng — tài khoản dùng proxy rẻ thường cũng là tài
khoản bị đẩy mạnh nhất. Bảng nói lên tương quan, không phải nguyên nhân.


---

## 7. Khi có sự cố

| Triệu chứng | Nguyên nhân thường gặp |
|---|---|
| API trả 401 | Thiếu hoặc sai `Authorization: Bearer <API_TOKEN>`. Trên dashboard thì bấm *sign out* rồi nhập lại |
| API trả 503 `Chua dat API_TOKEN` | Chưa sinh token. Chạy `gen_api_token.py`, dán vào `.env`, khởi động lại API |
| API trả 422 | Payload lồng nhau mà quên `-Depth 5` khi `ConvertTo-Json` |
| `Thieu VAULT_KEY trong .env` | Chưa chạy `gen_vault_key.py`, hoặc kết quả chưa được ghi vào `.env` |
| `Khong giai ma duoc` | `VAULT_KEY` hiện tại khác khoá đã dùng lúc mã hoá. Không khôi phục được — phải đăng nhập lại toàn bộ |
| Job `failed` với `rate governor` | Không phải lỗi. Đã chạm trần ngày, job tự lùi một tiếng |
| `Khong tim thay o soan noi dung` | Nền tảng đổi giao diện. Sửa `RECIPES` trong `adapters/browser.py` |
| `chua dang nhap lan nao` | Chạy `login_profile.py` cho tài khoản đó |
| Worker không nhặt job nào | Kiểm tra `docker compose ps`, và xem `scheduled_at` đã tới giờ chưa |
| Đổi schema xong lỗi cột | `alembic revision --autogenerate -m "mô tả"` rồi `python scripts/init_db.py` |
| `MEDIA_BACKEND=supabase but SUPABASE_URL... is not set` | Thiếu khoá trong `.env`. Cố ý báo lỗi thay vì âm thầm dùng local |
| Upload trả 502 `Could not store the file` | Kho từ xa từ chối. Chạy `python scripts/check_storage.py` để biết hỏng ở bước nào |
| `target is missing 'url' to comment on` | Nhóm đặt `post_kind=comment` mà chưa dán URL bài |
| `A comment needs body text` | Nội dung chỉ có tiêu đề. Bình luận chỉ lấy phần body |
| `No comment recipe for <nền tảng> yet` | Chưa có công thức bình luận cho nền tảng đó trong `COMMENT_RECIPES` |
| Chiến dịch lặp lại không sinh bản sao | Worker phải đang chạy — `repeat_tick` chạy phút thứ 11 mỗi giờ |
| Nhập CSV báo `is not a platform` | Cột `platform` sai chính tả. Thông báo liệt kê đủ các giá trị hợp lệ |
| Nhập CSV xong tài khoản không có mật khẩu | Gõ sai tên cột bí mật. Bản kiểm có liệt kê cột không nhận ra |
| Không nhận được cảnh báo | `ALERT_WEBHOOK_URL` rỗng, hoặc `telegram` mà thiếu `ALERT_TELEGRAM_CHAT_ID`. Lỗi gửi được ghi log `alert.failed`, không làm hỏng vòng quét |
| Ổ đĩa đầy vì media | Worker tự dọn bản biến thể cũ hơn `MEDIA_VARIANT_KEEP_DAYS` mỗi 4h30 sáng. Giảm số ngày nếu cần |

Xem log worker là cách nhanh nhất để biết chuyện gì đang xảy ra — mọi bước đều có ghi.

---

## 8. Thứ tự khuyến nghị cho tuần đầu

1. **Ngày 1** — cài đặt, chạy `demo_seed.py`, `demo_profiles.py`, `demo_takeover.py`,
   `demo_media.py` để thấy hệ thống làm gì.
2. **Ngày 1–2** — một tài khoản Reddit thật, đăng thử lên `r/test`. Đây là lúc bạn xác
   nhận toàn bộ pipeline đúng mà chưa mạo hiểm gì.
3. **Ngày 2–3** — mua thử **một dải proxy dân cư nhỏ**. Đừng ký hợp đồng lớn trước khi
   đo. Đây là khoản chi phí vận hành lớn nhất của bạn.
4. **Ngày 3–7** — 5 tài khoản Threads: tạo profile, đăng nhập tay, bật hoạt động nền,
   **chưa đăng bài gì cả**. Mục tiêu duy nhất là xem phiên có sống qua 14 ngày không.
5. **Sau đó** — thêm X, rồi YouTube, rồi Meta, rồi TikTok. Đúng thứ tự đó, vì mỗi nền
   tảng sẽ dạy bạn một dạng lỗi mới và bạn cần hạ tầng chịu lỗi trưởng thành dần.

Một điều nên nghĩ song song: tài khoản mới đăng lên tường của chính nó, khi chưa có bạn
bè, có lượng tiếp cận gần bằng không. Hệ thống này giải bài toán **xuất bản**; bài toán
**phân phối** — kết bạn, theo dõi, tham gia cộng đồng — vẫn còn nguyên và khối lượng
ngang ngửa.
