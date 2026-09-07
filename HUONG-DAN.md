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

**Bấm đúp `Start.cmd`.** Hết.

Nó tự làm đủ thứ tự: bật Docker Desktop nếu đang tắt → chờ Postgres và Redis thật sự
nhận kết nối → cập nhật schema → bật API, worker, dashboard → mở trình duyệt → in token
ra để bạn dán.

Hỏng ở bước nào thì nó **dừng lại ngay tại đó** kèm lệnh cần chạy để sửa, chứ không chạy
tiếp. Bật API khi Postgres chưa sống thì lỗi hiện ra là `connection refused` ở một chỗ
cách nguyên nhân thật ba tầng — cả buổi chiều đi tìm nhầm chỗ.

Bấm `Start.cmd` lại khi đang chạy thì nó **không bật trùng**, và tự dọn những cửa sổ rỗng còn sót từ lần trước.

Tắt: bấm **`Stop.cmd`**. Nó dừng ba tiến trình và các container, **không xoá dữ liệu**
(dùng `docker compose stop` chứ không phải `down`, vì một lần gõ nhầm `down -v` là mất
sạch cookie jar của mọi tài khoản).

Vài tuỳ chọn, nếu cần:

```bash
Start.cmd -Dev        # dashboard chạy hot-reload, dùng khi đang sửa giao diện
Start.cmd -Restart    # tắt sạch rồi bật lại
```

Bấm `Start.cmd` lần nữa khi đang chạy thì nó không bật trùng — chỉ báo cái nào đã sống.

**Ba cửa sổ terminal vẫn còn**, thu nhỏ dưới thanh tác vụ: API, Worker, Dashboard. Cố ý
để riêng — log của ba thứ đó là ba dòng khác nhau, trộn vào một cửa sổ thì lúc có sự cố
không đọc được gì. Tiến trình nào chết thì cửa sổ của nó **ở lại** kèm thông báo lỗi.

<details>
<summary>Chạy tay từng lệnh (khi cần debug)</summary>

```bash
docker compose up -d
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\uvicorn seeding.api.main:app --reload     # cửa sổ 1
.\.venv\Scripts\arq seeding.worker.settings.WorkerSettings # cửa sổ 2
npm run dev --prefix web                                     # cửa sổ 3
```

</details>

Rồi mở **`http://127.0.0.1:3000`**. Lần đầu nó hỏi token — `Start.cmd` đã in sẵn ra màn
hình để bạn dán. Token được lưu trong trình duyệt đó, không gửi đi đâu khác. Đổi token thì
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

`daily_cap` là trần **sau khi warm-up xong**. Hai ngày đầu (`WARMUP_QUIET_DAYS`, mặc định 2)
tài khoản **không đăng gì cả** — chỉ tương tác (xem 6.8). Sau đó bắt đầu ở 1 bài/ngày và tăng
dần lên `daily_cap` qua `WARMUP_DAYS` (mặc định 3 ngày). Job bị chặn vì chưa tới ngày thì được
lùi tới **mốc giờ vàng** kế tiếp (6.3), không phải +1 tiếng.

### 3.3. Soạn nội dung

Ảnh và video thì **kéo thả thẳng vào khung Media** ngay trong màn hình Compose — nó tải
lên và gắn vào bài trong một bước. Vẫn là cùng một kho: file vẫn hiện ở màn hình Media,
vẫn được kiểm tra trước khi xoá, vẫn được render lại riêng cho từng tài khoản lúc đăng.
Chỉ bỏ đi quãng đường đi lại.

Một bài mang một file. Thả ba cái vào thì nó lấy cái đầu và **nói rõ** hai cái kia không
được tải lên, thay vì im lặng bỏ.


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

### 5.1. Workspace

Bộ chọn **workspace** nằm trên thanh điều hướng, góc phải. Nó quyết định màn hình
Accounts hiển thị tài khoản nào, và là giá trị mặc định cho form soạn bài, tạo chiến
dịch, nhập CSV. Lựa chọn được nhớ lại khi bạn chuyển trang.

Màn hình **Workspaces** đổi tên và xoá được, kèm số thứ mỗi cái đang giữ. Xoá một
workspace còn tài khoản thì nó **từ chối** và nói rõ sắp mất gì — kể cả cookie jar, thứ
chỉ lấy lại được bằng cách đăng nhập tay lại từng tài khoản.

Proxy và thiết bị **không** thuộc workspace nào: chúng là hạ tầng dùng chung.

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

Bắt buộc: `platform`, `handle`. Còn lại tuỳ chọn. Persona chưa có sẽ được tạo tự động
theo tên trong file.

**Acc mua sẵn dùng thẳng, không phải sửa file.** Định dạng phổ biến

```
username|password|hotmail|pass_hotmail|cookie
```

nhập được nguyên xi. Hệ thống tự nhận ra ba thứ:

| Nó tự làm | Vì sao |
|---|---|
| Đoán dấu phân cách `\|`, `;`, tab, `,` | File acc gần như luôn dùng `\|`. Bắt đổi sang dấu phẩy còn làm hỏng dữ liệu — mật khẩu và **cookie thường có dấu phẩy bên trong** |
| `hotmail` → `recovery_email`, `pass_hotmail` → `recovery_password` | Tên cột của người bán, không phải tên của hệ thống |
| Không có cột `handle` thì `username` đóng cả hai vai | `username` cũng là một trường bí mật của Reddit nên không đổi thẳng được |

Không có cột `platform` thì chọn nền tảng ngay trên màn hình — một file 500 acc Facebook
không nên bắt lặp lại chữ "facebook" 500 lần.

Màn hình báo rõ cột nào đã được đọc thành cột nào, để bạn thấy mình không gõ nhầm.

### Cookie: bỏ qua được bước đăng nhập tay

Dòng nào có cột `cookie` sẽ được **tạo luôn profile kèm phiên đăng nhập** — không phải
chạy `login_profile.py` cho acc đó nữa. Với vài trăm acc thì đây là bước chậm nhất trong
cả quy trình, nên đó là lý do cột này tồn tại.

Nhận cả ba dạng: chuỗi `ten=giatri; ten2=giatri2`, mảng JSON xuất từ tiện ích cookie,
và storage state đầy đủ của Playwright.

Tick **give each new profile a free, tested proxy** để mỗi profile nhận một proxy còn
rảnh — *một acc, một proxy, không dùng chung*. Không đủ proxy thì nó nói rõ còn thiếu
bao nhiêu chứ không im lặng để trống.

> **Cookie hợp lệ về cú pháp không có nghĩa là nó còn sống.** Cookie được cấp cho *một*
> thiết bị tại *một* địa chỉ. Dán nó vào profile có fingerprint khác và đi ra bằng proxy
> khác chính là tình huống mà nền tảng dùng cookie để phát hiện. Gắn proxy cùng quốc gia
> với acc, và chuẩn bị tinh thần một phần rơi vào hàng đợi tiếp quản.

Hệ thống kiểm giúp phần kiểm được: thiếu cookie phiên (`c_user`/`xs` với Facebook,
`sessionid` với Instagram…) thì nó **báo ngay lúc nhập** thay vi để bạn phát hiện lúc
đăng bài hỏng.

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

Màn hình **Hours**. Bấm *edit* ở một nền tảng để mở ra bảy ngày trong tuần.

Ba nút đặt nhanh: **all week**, **Mon–Fri**, **Sat–Sun**. Rồi sửa lại từng ngày nếu cần.
Ngày nào không đặt riêng thì chạy 7h–23h theo giờ máy chủ.

Đặt cuối tuần khác ngày thường không phải để cho đẹp: người thật không thức dậy và đi ngủ
đúng một khung giờ bảy ngày liền, và dùng chung một khung cho cả tuần cũng là một mẫu
hình — chỉ kín đáo hơn.

Giờ kết thúc chọn được **24:00** nghĩa là chạy đến nửa đêm.

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


### 6.5. Chạy được bao nhiêu tài khoản trên một máy

Con số này không phải cảm tính — nó tính ra được từ chính hằng số trong code.

Mỗi bài đăng kéo theo **6 lần hoạt động nền** (`ACTIVITY_PER_POST`), mỗi lần trung bình
**132 giây** trình duyệt thật. Worker chạy tối đa **5 phiên song song** (`max_jobs`), và
khung giờ thức mặc định là 16 tiếng. Ngân sách một ngày vì thế là **288.000 giây trình
duyệt**.

| Số acc | daily_cap | Job nền/ngày | Giờ trình duyệt | % ngân sách |
|---:|---:|---:|---:|---:|
| 50 | 2 | 600 | 24,6h | 31% |
| 50 | 3 | 900 | 36,9h | 46% |
| 100 | 2 | 1.200 | 49,2h | 61% |
| 100 | 3 | 1.800 | 73,8h | **92% — sát trần** |
| 150 | 3 | 2.700 | 110,6h | **138% — quá tải** |
| 200 | 3 | 3.600 | 147,5h | **184% — quá tải** |

**Trần thực tế của một máy: khoảng 100 tài khoản với cap 3, hoặc 150 với cap 2.**

Quá tải không báo lỗi gì cả — job chỉ đơn giản là chạy trễ dần, rồi tràn ra ngoài khung
giờ thức. Đó là kiểu hỏng tệ nhất: tài khoản bắt đầu hoạt động lúc 2 giờ sáng, đúng thứ
mà cả hệ thống này dựng ra để tránh.

Ba thứ khác cũng chạm trần quanh mốc đó:

- **Kiểm tra sức khoẻ**: 10 acc mỗi giờ = 240 lượt/ngày. Với chu kỳ 12 tiếng thì mỗi acc
  cần 2 lượt/ngày → quá **120 tài khoản** là lịch kiểm tra bắt đầu trễ.
- **RAM**: 5 phiên song song × ~400MB = **2GB** chỉ riêng trình duyệt.
- **Proxy**: một acc ↔ một proxy, **không bao giờ xoay**. 100 acc là 100 proxy. Đây
  thường là khoản đắt nhất, và không có cách lách nào mà không đánh đổi bằng tài khoản.

Muốn vượt trần thì tăng `max_jobs` trong `worker/settings.py` (đổi bằng RAM), hoặc chạy
worker thứ hai trên máy khác cùng trỏ về một Postgres/Redis. Job được giành bằng câu
`UPDATE ... WHERE status = SCHEDULED` nguyên tử, nên nhiều worker không giẫm chân nhau.

Màn hình Accounts, Schedule và Compose đều **phân trang 50 dòng** kèm ô tìm kiếm và bộ
lọc (nền tảng, trạng thái). Số trên tab là **tổng thật**, không phải số dòng đang hiện.

Hai danh sách cố ý **không** phân trang, vì chúng là hàng đợi việc phải làm chứ không
phải bảng để duyệt: *No profile yet* và *Sign in by hand*. Một hàng đợi chỉ hiện trang
đầu thì những tài khoản ở trang hai sẽ nằm đó mãi.


### 6.6. Tương tác chéo: follow, thả cảm xúc, chia sẻ lại

Màn hình **Network**. Bấm *Grow the graph a little* để thêm vài lượt theo dõi giữa các
tài khoản của bạn.

Một bài không có tương tác nào thì không lan được — nhưng đây cũng là thứ dễ mất cả cụm
nhất. Nền tảng bắt trại tài khoản bằng **đồ thị hành vi** dễ hơn nhiều so với fingerprint:
fingerprint hỏng thì mất một acc, đồ thị hỏng thì một acc bị gắn cờ sẽ dẫn ra tất cả
những acc còn lại.

Nên hệ thống **không cho** bạn tạo ra các hình dạng lộ liễu, và không có nút tắt:

- Tối đa **8 cạnh mới mỗi ngày** trên toàn hệ thống. Đồ thị phải lớn lên từ từ.
- Mật độ tối đa **15%** (từ 10 tài khoản trở lên). Đồ thị dày là vật thể không tồn tại
  trong tự nhiên.
- Một tài khoản theo dõi tối đa **12** tài khoản nội bộ — không ai được thành trung tâm.
- Chỉ ~25% lượt theo dõi được đáp lại.
- Khi một bài lên, chỉ **một phần** người theo dõi tương tác, **sau ít nhất 18 phút**, rải
  trong nhiều giờ. Chia sẻ lại rất hiếm (6%).

Reddit không nằm trong đồ thị — nó đi bằng API, không có profile trình duyệt.

Cạnh mới tạo ở trạng thái **planned**. Nó chỉ thành **done** khi worker mở trình duyệt,
bấm được, và **thấy nút đổi thành Following**. Không thấy thì báo thất bại — vì nếu coi
cạnh chưa bấm là đã xong, mọi con số mật độ ở trên đều sai.

> **Con số hệ thống không đo được:** nó chỉ thấy cạnh giữa các tài khoản của bạn. Nó
> không biết mỗi acc theo dõi bao nhiêu người **thật** bên ngoài — mà đó mới là tỷ lệ
> quan trọng nhất. Theo dõi 8 acc nội bộ và 300 người thật là bình thường; cùng 8 cạnh đó
> mà không theo dõi ai khác thì là cái bẫy. Trong database hai trường hợp giống hệt nhau.
> Cảnh báo này luôn hiện trên màn hình Network, cố ý.


### 6.8. Nuôi hướng ra ngoài trên TikTok: thả tim, theo dõi, bình luận người lạ

Tương tác chéo (6.6) nối các tài khoản **của bạn** với nhau. Nhưng một tài khoản mới mà chỉ
tương tác với sáu tài khoản mới khác là một cụm kín — thứ dễ nhìn ra nhất. Nên trên TikTok
hệ thống còn tự nuôi **hướng ra ngoài**: đọc For You *của chính tài khoản đó* (qua proxy của
nó), thả tim vài video đang lên, theo dõi vài creator lạ, thỉnh thoảng bình luận.

- Chạy hằng ngày cùng lúc với hoạt động nền, không phải bật gì thêm. Tắt bằng
  `TIKTOK_INTERACT_VIA_HTTP=false` trong `.env`.
- Ngân sách một ngày cố ý nhỏ: 4–8 thả tim, 1–3 theo dõi, 0–2 bình luận. Ngày đầu tiên chỉ
  một nửa và không bình luận. Sửa trong `src/seeding/core/outreach.py`.
- Bình luận chỉ vào video **đã thả tim** và đi sau nó ít nhất 8 phút. Câu bình luận lấy từ
  một bộ tiếng Việt đời thường trong `core/tiktok_interact.py` — thêm bớt ở đó.
- Tất cả đi bằng HTTP qua signer (như đăng bài), không mở trình duyệt: mỗi hành động ~1–3
  giây qua proxy dân cư. Thả tim và theo dõi được thử lại khi không rõ kết quả; **bình luận
  thì không** — gửi lại là hai bình luận giống nhau, nên nó vào hàng đợi chờ bạn (6.1).

Xem các job này ở màn hình Activity của tài khoản: `engage` = thả tim, `follow`, `comment`,
cột target là video hoặc trang cá nhân của người lạ.

### 6.7. Điện thoại thật (Android)

Tab **Devices** trong màn hình Accounts.

Trước hết bấm *Scan for phones*. Nó nói ngay còn thiếu gì — **tất cả** cùng lúc, không
phải từng thứ một:

1. `adb` chưa có trong PATH → cài [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools)
2. Appium chưa cài → `pip install Appium-Python-Client`
3. Máy chưa bật USB debugging, hoặc chưa bấm *cho phép*

Máy đang cắm mà chưa đăng ký sẽ hiện trong phần *Not registered yet*. Bấm **Add device**,
dán serial vào. Hệ thống **không tự thêm** — một cái điện thoại cắm vào để sạc cũng hiện
ra trong `adb devices`.

Rồi gán mỗi máy cho một tài khoản và một proxy. Ràng buộc giống hệt bên profile: **một
acc, một máy, một proxy, không xoay.**

> **iOS thì không chạy được trên Windows.** Không phải thiếu công sức: tự động hoá app
> iOS bắt buộc phải ký WebDriverAgent bằng Xcode (chỉ có trên macOS), và iOS Simulator
> không cài được app từ App Store. Muốn iOS thật thì cần máy Mac và iPhone thật.

**Phần điều khiển app chưa chạy được** — mở app, gõ, bấm đăng nằm ở `adapters/android.py`
và cần Appium. Hiện tại tab này quản lý được thiết bị, chưa đăng bài qua chúng được.


---

## 7. Khi có sự cố

| Triệu chứng | Nguyên nhân thường gặp |
|---|---|
| `Start.cmd` dừng ở *Khong co file .env* | Chưa cấu hình lần đầu. Nó in sẵn ba lệnh cần chạy |
| `Start.cmd` dừng ở *Postgres khong len* | Docker Desktop có vấn đề. `docker compose logs postgres` |
| Bấm `Start.cmd` mà cửa sổ nhấp nháy rồi tắt | Chạy nó từ terminal để đọc lỗi: `.\Start.cmd` |
| Script cũ gọi `/accounts` bị lỗi | API giờ trả `{items, total, limit, offset}` chứ không phải mảng trần. Đổi thành `.items` |
| Ô chọn tài khoản thiếu acc | Nó chỉ tải 200 cái đầu khớp bộ lọc — gõ vào ô tìm kiếm để thu hẹp |
| `no interaction recipe for <nền tảng> yet` | Chưa có công thức follow cho nền tảng đó trong `browser/interact.py` |
| `clicked follow but the button never changed` | Selector đúng nhưng chưa xác nhận được. Kiểm tay rồi sửa `RECIPES` |
| Bấm *Grow the graph* mà tạo 0 cạnh | Đã chạm trần mật độ, hoặc nền tảng đó chưa đủ 2 acc còn sống |
| Máy hiện `unauthorized` | Chưa bấm *cho phép gỡ lỗi USB* trên màn hình điện thoại |
| `adb is not on PATH` | Cài Android Platform Tools rồi thêm vào PATH, mở lại terminal |
| Worker chết với `UnicodeEncodeError` | Đã sửa — console Windows là cp1252, `_force_utf8_output()` ép UTF-8. Nếu vẫn gặp thì báo |
| `NotInstalledGeoIPExtra` khi mở profile | Thiếu extra geoip. `pip install -e .` là đủ — nó đã nằm trong `pyproject.toml` |
| `InvalidIP: Failed to get IP address` | Proxy của profile đó chết. **Đây là hành vi đúng**: hệ thống từ chối mở còn hơn chạy bằng IP thật của bạn. Sửa proxy hoặc bỏ gán nó |
| Ô *Workspace* chọn xong không thấy đổi gì | Đã sửa — trước đây danh sách persona không lọc theo workspace nên ô đó không điều khiển gì |
| Ô chọn workspace đầy dòng *Library test* | Rác do bộ test cũ để lại. Vào màn hình **Workspaces** xoá; fixture giờ tự dọn |
| Thanh tác vụ đầy cửa sổ *Seeding - API* giống nhau | Đã sửa. Cửa sổ mở bằng `/k` để khi sập còn đọc được lỗi, nhưng `Stop.cmd` cũ chỉ giết tiến trình theo cổng nên vỏ cmd ở lại. Giờ nó đóng cả cây, và `Start.cmd` tự dọn vỏ rỗng |
| Nhập CSV báo `has no persona, and no default was given` | File không có cột `persona`. Chọn một persona mặc định ở ô *Persona for rows that name none* |
| Acc nhập bằng cookie nhưng vẫn như chưa đăng nhập | Cookie chỉ có phần thiết bị (`datr`, `sb`) chứ không có phần phiên. Bản kiểm có báo — đọc phần cảnh báo màu vàng |
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
