# Seeding CMS

CMS tự host cho nhiều tài khoản seeding đăng lên trang cá nhân của chính chúng.

Ràng buộc chi phối toàn bộ thiết kế: **chỉ đăng lên trang cá nhân, và mọi tài khoản
đều là acc seeding.** Với ràng buộc đó thì không API chính thức nào phục vụ được —
Facebook bỏ quyền đăng lên trang cá nhân từ Graph v3.0 (2018), X thì mỗi acc phải có
developer account riêng và trả tiền theo lượt, TikTok đòi audit cấp doanh nghiệp.
Reddit là ngoại lệ duy nhất và là ngoại lệ thật sự dùng được: mỗi tài khoản tự đăng ký
một *script app*, miễn phí, và vì mỗi acc là một OAuth client riêng nên hạn mức cộng dồn.

Vì vậy automation không phải phương án dự phòng — nó **là** sản phẩm.

**Trạng thái:** giai đoạn 01–04 đã dựng xong. Riêng selector đăng bài **chưa kiểm
chứng** — xem mục Giai đoạn 03 bên dưới.

> Muốn bắt tay vào dùng ngay thì đọc **[HUONG-DAN.md](HUONG-DAN.md)** — đi theo đúng thứ
> tự bạn sẽ làm, từ máy trắng đến bài đăng đầu tiên. Tài liệu này giải thích *vì sao*.

---

## Chạy thử

```bash
docker compose up -d
```

```bash
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
```

```bash
cp .env.example .env && .venv/Scripts/python scripts/gen_vault_key.py >> .env
```

```bash
.venv/Scripts/python -m camoufox fetch && .venv/Scripts/python scripts/init_db.py
```

Hai kịch bản kiểm chứng, không gọi tới mạng xã hội nào:

```bash
.venv/Scripts/python scripts/demo_seed.py
```

```bash
.venv/Scripts/python scripts/demo_profiles.py
```

```bash
.venv/Scripts/python scripts/demo_takeover.py
```

```bash
.venv/Scripts/python scripts/demo_media.py
```

API và worker:

```bash
.venv/Scripts/uvicorn seeding.api.main:app --reload
```

```bash
.venv/Scripts/arq seeding.worker.settings.WorkerSettings
```

Tài liệu API tại `http://127.0.0.1:8000/docs`.

---

## Giai đoạn 01 — pipeline, chưa đụng trình duyệt

Chứng minh vòng đời chạy đúng trên Reddit trước khi phải đánh nhau với anti-detect.

| Cơ chế | Ở đâu | Vì sao có |
|---|---|---|
| **Stagger** | `core/planner.py` | Mười acc đăng trong cùng một giây là mẫu hình dễ phát hiện nhất. Mỗi job lệch ngẫu nhiên trong `stagger_window_seconds`. |
| **Biến thể riêng từng acc** | `core/spintax.py` | Nhiều acc đăng chuỗi text giống hệt nhau là tín hiệu spam rõ nhất. RNG có seed cố định theo acc nên lập kế hoạch lại không đổi nội dung. |
| **Idempotency key** | `core/planner.py` | `sha256(campaign, group, account)` làm unique index. Ngăn retry biến thành đăng trùng — và bạn sẽ retry rất nhiều. |
| **Warm-up ramp** | `core/ratelimit.py` | Acc mới bắt đầu ở 1 bài/ngày, tăng dần lên `daily_cap`. Trần nằm trong DB chứ không hardcode. |

Bị rate governor chặn thì job **không** bị đánh thất bại — nó lùi lại một tiếng, lý do
ghi vào `last_error`.

## Giai đoạn 02 — profile store và vòng đời phiên

Phần khó nhất không phải "đăng bài" mà là **giữ cho tài khoản còn sống**.

| Cơ chế | Ở đâu | Vì sao có |
|---|---|---|
| **Két bí mật** | `core/vault.py` | Mật khẩu, TOTP seed, mật khẩu proxy và cookie jar đều mã hoá Fernet trước khi xuống DB. Cookie jar chính là phiên đăng nhập — ai có nó là vào được tài khoản. |
| **Fingerprint ghim** | `core/fingerprint.py` | Sinh một lần bằng preset của chính Camoufox rồi không bao giờ sinh lại. Fingerprint đổi giữa các phiên của cùng một acc là bất thường rõ hơn là một fingerprint tầm thường nhưng ổn định. |
| **Một acc = một proxy** | `core/profiles.py` | `bind_proxy` từ chối đổi proxy của profile đã gắn. Xoay IP giữa các phiên của cùng một tài khoản hại hơn là giữ một IP dân cư cố định. |
| **Đăng nhập một lần** | `scripts/login_profile.py` | Đăng nhập là hành động rủi ro nhất. Làm bán thủ công một lần, giữ phiên mãi mãi, không bao giờ auto-login lại. |
| **Ngưỡng chờ người** | `core/profiles.py` | Hai lần health check thất bại liên tiếp thì acc chuyển `NEEDS_HUMAN` và bị loại khỏi hàng đợi tự động. |

### Đưa một tài khoản vào hệ thống

1. `POST /accounts` kèm `secrets` (được mã hoá ngay, không bao giờ đọc ngược ra qua API).
2. `POST /proxies` rồi `POST /profiles` với `account_id` và `proxy_id`.
3. Đăng nhập bằng tay — script mở đúng fingerprint và proxy của profile đó:

```bash
.venv/Scripts/python scripts/login_profile.py threads em_haiyen
```

Bạn đăng nhập trong cửa sổ vừa mở (kể cả 2FA và captcha), quay lại terminal ấn Enter,
script lưu cookie jar đã mã hoá. Khi phiên chết, chạy lại đúng lệnh này — **đừng viết
code tự đăng nhập lại**, đó là cách nhanh nhất để mất tài khoản.

`GET /accounts/needs-human` là hàng đợi những acc đang cần bạn.

## Giai đoạn 03 — automation worker, hoạt động nền, tiếp quản

| Cơ chế | Ở đâu | Vì sao có |
|---|---|---|
| **Nhịp giả người** | `browser/humanize.py` | Gõ cả đoạn trong một sự kiện, đăng ngay giây đầu vào trang, không bao giờ cuộn — đó là các dấu vết máy móc rõ nhất. Gõ từng ký tự với độ trễ thay đổi, nghỉ lâu hơn ở dấu câu, xem feed trước khi đăng. |
| **Phân biệt ba tình huống** | `browser/checkpoints.py` | Checkpoint → chờ người. Lỗi tạm → retry. Bị khoá hẳn → bỏ luôn, đừng làm bẩn hàng đợi. Đoán sai hướng nào cũng tốn kém. |
| **Hoạt động nền** | `core/activity.py` | Acc chỉ đăng bài rồi biến mất là mẫu bot rõ nhất. Mỗi bài đăng đi kèm 6 lần "sống" không đăng gì, rải đều trong khung 7h–23h. |
| **Hàng đợi tiếp quản** | `core/takeover.py` | Gặp checkpoint thì acc *và* job cùng dừng, và hệ thống nhớ job nào bị kẹt. Giải xong thì job hẹn lại sau 6 tiếng chứ không chạy ngay — vừa qua checkpoint mà đăng liền là đúng cái nhịp đang bị soi. |

Acc quay về `WARMING` chứ không phải `ACTIVE` sau khi được giải: vừa qua checkpoint thì
đi chậm lại một nhịp.

```bash
.venv/Scripts/python scripts/takeover.py list
```

```bash
.venv/Scripts/python scripts/takeover.py open threads em_haiyen
```

Lệnh `open` mở Camoufox đúng fingerprint, proxy và cookie của acc đó, in sẵn mã 2FA nếu
đã lưu `totp_seed`. Giải xong thì `resolve` (hoặc `abandon` nếu acc không cứu được).

### Selector đăng bài chưa được kiểm chứng

`RECIPES` trong [adapters/browser.py](src/seeding/adapters/browser.py) là **điểm xuất
phát, không phải đã xác minh** — không thể kiểm chúng nếu không có tài khoản thật.
Chúng được gom thành bảng khai báo một chỗ để sửa nhanh, và adapter thất bại ồn ào kèm
danh sách những gì đã thử. Ba nguyên tắc trong đó đáng giữ:

- **Không khớp selector là lỗi code, không phải lỗi tài khoản** — không đánh
  `needs_human`, vì người vận hành mở trình duyệt ra cũng không sửa được gì.
- **Không tin là đã đăng cho tới khi thấy dấu hiệu thật.** Báo thành công nhầm nguy
  hiểm hơn báo thất bại nhầm: job sẽ không được thử lại, mà bài thì chưa bao giờ lên.
- **`REACT` cố ý chưa bấm thật.** Thả cảm xúc là hành động ghi lại được trên nền tảng;
  bấm nhầm vào thứ khác còn tệ hơn không bấm.

Cơ chế gõ chữ *đã* được kiểm chứng trên `contenteditable` thật — thứ mà cả Threads và X
đều dùng thay cho `<textarea>`.

## Túi hashtag

Không phải một khối hashtag cố định dán vào mọi bài — mười tài khoản đeo đúng một dãy
thẻ giống hệt nhau là **cùng một dấu vết trùng lặp như văn bản giống nhau**. Nhiều công
cụ seeding cho dán một khối chung, và đó chính là chỗ lộ.

Thay vào đó bạn tạo một *túi* rồi đặt chỗ dành trong bài:

```
[[tags:tech:3]]
```

Planner rút 3 thẻ khác nhau cho từng tài khoản, dùng đúng RNG có seed như spintax — nên
lập kế hoạch lại vẫn ra bài cũ, mà mỗi acc một tổ hợp riêng.

Tác dụng đo được: một túi 12 thẻ rút 3 cho **1.320 tổ hợp**, nhân vào số tổ hợp spintax.
Template mẫu đi từ 192 lên 253.440 tổ hợp, nguy cơ trùng với 5 tài khoản rơi từ 5% xuống
0%. Thêm một túi hashtag hạ nguy cơ trùng nhanh hơn bất kỳ nhánh spintax nào.

Gõ sai tên túi thì chỗ dành **hiện nguyên văn** thay vì biến mất — để bạn nhìn thấy
ngay, chứ không phải bài lên thiếu hashtag mà không ai biết.

---

## Giai đoạn 04 — biến thể media

Văn bản khác nhau là chưa đủ. Mười acc upload cùng một file giống hệt từng byte thì hệ
thống nhận diện nội dung trùng bắt được ngay. `core/media.py` chạy ffmpeg để cắt viền,
đổi tốc độ, chỉnh sáng/bão hoà, thêm nhiễu, xoá sạch metadata và re-encode — mỗi acc một
công thức riêng, sinh từ seed cố định của `(campaign, account)` nên lập kế hoạch lại
không render lại.

Render diễn ra **lúc sắp đăng**, không phải lúc lập kế hoạch: một chiến dịch 100 acc mà
render ngay thì phải chờ vài phút mới thấy được lịch.

### Nói thẳng về mức độ hiệu quả

Đây là số đo thật trên video mẫu, in ra bởi `demo_media.py` — không phải ước lượng:

| Mức độ | pHash lệch so với gốc | pHash lệch giữa các bản | Nghĩa là |
|---|---|---|---|
| `subtle` | 2 | **0–0** | Mắt thường không thấy. Bộ so khớp tri giác vẫn coi cả 5 bản là **một file**. |
| `moderate` | 10–16 | 0–8 | Bắt đầu dịch, nhưng vẫn có cặp trùng khít nhau. |
| `aggressive` | 18–32 | 4–34 | Thật sự khác nhau — đổi lại là nhìn ra được. |

Hash file thì **chắc chắn** khác nhau ở cả ba mức (5/5). Đó là điều kiện cần và nó rẻ.
Nhưng nếu nền tảng so khớp tri giác tốt thì tiền không nằm ở đây: câu trả lời thật là
**nội dung gốc khác nhau cho từng nhóm tài khoản**.

Vì vậy module này **đo và báo cáo khoảng cách pHash thay vì khẳng định "đã đủ khác"**.
Bạn nhìn số rồi tự quyết `MEDIA_STRENGTH` trong `.env`.

Đo thật cũng lộ một vấn đề: ở mức `moderate`, **acc-1 và acc-3 ra pHash y hệt nhau**.
Trùng như vậy là mất hết ý nghĩa của việc sinh biến thể, nên `mediastore.ensure_variant`
nhận danh sách pHash đã dùng trong chiến dịch và rút lại với seed khác nếu trùng. Sau khi
bật cơ chế đó, mức `moderate` đi từ 0–8 lên 2–16.

---

## Cấu trúc

```
Start.cmd              bật tất cả bằng một lần bấm; dừng lại ngay khi một bước hỏng
Stop.cmd               tắt tất cả, giữ nguyên dữ liệu
scripts/launch.ps1     việc thật nằm ở đây

src/seeding/
  models.py            Workspace → Persona → Account → Profile → Proxy
                       Content → Variant, Campaign → Group → PostJob → Attempt
                       SessionEvent (nhật ký vòng đời phiên)
  core/vault.py        Fernet + TOTP; mọi thứ nhạy cảm đi qua đây
  core/fingerprint.py  ghim preset Camoufox, loại preset không mở được
  core/profiles.py     tạo profile, gắn proxy, lưu cookie, theo dõi sức khoẻ
  core/spintax.py      {a|b|c} lồng nhau, RNG có seed
  core/planner.py      bung campaign thành ma trận job, gán lịch
  core/ratelimit.py    trần theo ngày + ramp warm-up
  core/activity.py     rải hoạt động nền trong khung giờ thức
  core/takeover.py     hàng đợi chờ người: mở, giải, bỏ
  core/media.py        ffmpeg sinh biến thể; đo pHash thay vì khẳng định
  core/mediastore.py   cache theo công thức, tránh trùng pHash trong chiến dịch
  core/hashtags.py     túi hashtag rút ngẫu nhiên theo từng tài khoản
  core/storage.py      kho file: thư mục trên máy, hoặc Supabase Storage
  core/recurring.py    chiến dịch lặp lại: nhân bản theo kỳ, bỏ kỳ đã lỡ
  core/survival.py     tài khoản sống được bao lâu, cắt theo proxy/warm-up/nhịp
  core/bulk.py         nhập tài khoản hàng loạt từ CSV, kiểm trước khi tạo
  core/graph.py        tương tác chéo: luật mật độ, đối xứng, nhịp — không tắt được
  core/devices.py      điện thoại thật: tìm qua adb, đối soát, preflight
  core/cookies.py      đọc cookie của acc mua sẵn thành storage state Playwright
  core/alerts.py       báo ra ngoài khi hàng đợi tiếp quản có người mới
  browser/session.py   mở Camoufox đúng danh tính; kiểm tra phiên còn sống
  browser/humanize.py  gõ, cuộn, dừng đọc theo nhịp người
  browser/checkpoints.py  phân biệt checkpoint / lỗi tạm / bị khoá
  browser/activity.py  chạy một lần "sống" không đăng gì
  browser/interact.py  theo dõi / thả cảm xúc / chia sẻ lại — chỉ báo xong khi thấy bằng chứng
  adapters/base.py     giao diện chung cho cả hai lane
  adapters/reddit.py   PRAW, chạy trong to_thread vì PRAW đồng bộ
  adapters/browser.py  đăng bài bằng Camoufox — RECIPES cần kiểm chứng
  worker/tasks.py      tick, activity_tick, health_sweep, plan_activity, repeat_tick
  api/routes.py        vận hành: tài khoản, proxy, profile, lịch, tiếp quản
  api/routes_library.py  kho media và túi hashtag
  api/security.py      token dùng chung, fail-closed

web/                   dashboard Next.js 15 (App Router, Tailwind 4) — giao diện tiếng Anh
  src/app/page.tsx           Overview
  src/app/compose/           soạn bài, chèn hashtag, gắn media, xem trước bài thật
  src/app/media/             kho media: kéo-thả tải lên, ảnh xem trước, xoá
  src/app/hashtags/          túi hashtag: tạo, sửa, xoá
  src/app/schedule/          ba cột Campaigns → Groups → Posts
  src/app/accounts/          tài khoản, profile, proxy — sửa/xoá tại chỗ, test proxy
  src/app/takeovers/         hàng đợi tiếp quản + mã 2FA
  src/app/network/           đồ thị tương tác chéo, mật độ, cảnh báo
  src/components/devices     tab thiết bị thật trong màn hình Accounts
  src/components/workspace   workspace đang chọn, dùng chung cho cả dashboard
  src/app/workspaces/        đổi tên, xoá, và xem mỗi workspace đang giữ gì
  src/app/analytics/         tỷ lệ sống sót theo proxy, warm-up, nhịp đăng
  src/app/settings/          khung giờ thức theo từng nền tảng và từng ngày trong tuần
  src/components/token-gate  chắn dashboard cho tới khi có token dùng được
  src/lib/api.ts             một chỗ duy nhất gọi API
```

---

## Kiểm thử

```bash
.venv/Scripts/pytest -q
```

60 test nhanh, không cần trình duyệt. Riêng test mở Camoufox thật bị loại mặc định:

```bash
.venv/Scripts/pytest -m browser
```

10 test này không đụng tới mạng xã hội nào. Chúng chứng minh **canvas fingerprint ổn
định qua các lần mở của cùng một profile, và khác nhau giữa hai profile** — đó mới là
thứ nối hai tài khoản lại với nhau, chứ không phải user agent. User agent giống nhau
giữa các profile là *đúng*: người dùng Firefox thật trên Windows đều chung một chuỗi UA.
Nhóm còn lại dựng trang tại chỗ bằng `set_content()` để kiểm cơ chế gõ chữ, tìm selector
và nhận diện checkpoint trên DOM thật.

Test nhịp giả người dùng đồng hồ giả — đo được *hành vi* (độ trễ có thay đổi không, có
nghỉ lâu hơn ở dấu câu không) mà không phải chờ thật.

Test ffmpeg cũng bị loại mặc định vì mỗi lần encode tốn vài giây:

```bash
.venv/Scripts/pytest -m media
```

14 test này dựng video mẫu tại chỗ bằng `testsrc`, không cần file thật.

Trước khi commit:

```bash
.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check . && .venv/Scripts/pytest -q
```

---

## Hai điều học được khi dựng giai đoạn 02

**Camoufox tự quản fingerprint.** Ban đầu module `core/fingerprint.py` sinh fingerprint
bằng BrowserForge rồi truyền vào. Sai — Camoufox bỏ qua và cảnh báo, vì user agent phải
khớp với phiên bản Firefox thật của binary, không thì chính fingerprint đó tự mâu thuẫn.
Cách đúng là lấy preset của Camoufox, lưu nguyên dạng config phẳng, trả lại qua tham số
`config=`. Config phẳng còn mang theo `canvas:seed`, `audio:seed` và `fonts:spacing_seed`
— đó mới là thứ làm nên danh tính ổn định.

**Khoảng một phần các preset không mở được trình duyệt.** Chúng chứa cặp WebGL mà chính
Camoufox không tra được dữ liệu. Vì fingerprint ghim vĩnh viễn, một profile tạo nhầm
preset đó sẽ hỏng mãi mãi. `is_launchable()` hỏi thẳng cơ sở dữ liệu WebGL của Camoufox
— đúng đoạn code nó chạy lúc khởi động — nên không bao giờ lệch với thực tế.

---

## Xác thực

Một token dùng chung, đặt ở `API_TOKEN` trong `.env`, bắt buộc trên mọi route trừ
`/health`. **Fail-closed**: chưa đặt token thì API trả 503 chứ không chạy mở — một hệ
thống giữ cookie jar của hàng chục tài khoản và sinh được mã 2FA mà "tạm để mở" là cách
mất sạch.

Đây không phải hệ thống người dùng, và cố ý không phải: bảng users, phiên đăng nhập,
quên mật khẩu chỉ làm tăng bề mặt tấn công mà không giải quyết được gì ở quy mô vài
người vận hành. Nhưng vì vậy nó **chỉ đủ cho localhost** — đừng mở ra Internet.

```bash
.venv/Scripts/python scripts/gen_api_token.py
```

15 test trong [test_auth.py](tests/test_auth.py) quét cả danh sách route thay vì tin
rằng không có route nào bị bỏ sót, kể cả route sinh mã 2FA.

---

## Ba tầng Campaign → Group → Post

Màn hình Schedule chia ba cột, bấm dọc theo hàng để lọc dần — cùng cách Ads Manager
tách Campaign / Ad set / Ad.

Tầng giữa có lý do tồn tại: **một chiến dịch có thể nhắm nhiều nền tảng cùng lúc.** Cùng
một nội dung, một nhóm đẩy lên Reddit `r/test`, một nhóm khác lên Threads — mỗi nhóm có
mục tiêu và danh sách tài khoản riêng, nhưng chung nội dung gốc và chung cửa sổ rải.

Thêm nhóm vào chiến dịch đã chạy được: nó tự lập lịch cho riêng nhóm mới, và
`idempotency_key` đảm bảo các nhóm cũ không bị sinh job trùng.

---

## Xoá thì hỏi lại, và hỏi vì lý do cụ thể

Mỗi lệnh xoá đều kiểm cái gì đang tham chiếu tới nó trước, và câu từ chối nói rõ mất gì:

| Xoá | Bị chặn khi | Vì sao |
|---|---|---|
| Proxy | còn profile gắn vào | Xoá đi thì profile đó mở trình duyệt bằng **IP thật của máy bạn** — không cho force. |
| Profile | còn phiên đăng nhập | Vứt cả cookie jar lẫn fingerprint đã ghim; tạo lại sẽ là một máy khác hẳn. |
| Media | còn nội dung dùng | Bài sẽ mất file lúc render. |
| Nội dung | có chiến dịch dựng từ nó | Bài của chiến dịch đó mất nguồn. |
| Tài khoản / chiến dịch | đã có bài lên thật | Mất lịch sử trong khi bài vẫn còn trên nền tảng. |

Trừ proxy, tất cả đều force được — nhưng phải nói rõ ý định.

---

## Kho media: máy này hay Supabase

`MEDIA_BACKEND=local` (mặc định) giữ mọi thứ trong `MEDIA_ROOT`. `MEDIA_BACKEND=supabase`
đẩy file gốc và ảnh xem trước lên bucket của bạn.

Chia việc có chủ ý — **không phải thứ gì cũng lên kho từ xa**:

| Thư mục | Là gì | Đi đâu |
|---|---|---|
| `sources/` | File gốc, **không sinh lại được** | Lên kho từ xa nếu bật |
| `thumbs/` | Ảnh xem trước, nhẹ, dashboard cần | Lên kho từ xa nếu bật |
| `variants/` | Bản render cho từng tài khoản | **Luôn ở máy** |

Biến thể ở lại máy vì ba lý do: chúng sinh lại được bất cứ lúc nào từ công thức có seed,
chúng bị dọn sau `MEDIA_VARIANT_KEEP_DAYS`, và ffmpeg cần đường dẫn thật để đọc. Đẩy
chúng lên là trả tiền băng thông cho thứ sẽ bị xoá trong hai tuần.

Bật lên:

```bash
.venv/Scripts/python scripts/check_storage.py
```

Chạy cái đó **ngay sau khi đổi `MEDIA_BACKEND`**, trước khi upload gì quan trọng. Nó ghi
lên, đọc về, so từng byte, rồi xoá đi. Cấu hình sai mà không kiểm thì lỗi chỉ lộ ra lúc
worker sắp đăng bài — và lúc đó là muộn.

Thiếu khoá thì `build()` **báo lỗi ngay chứ không âm thầm quay về local**: âm thầm dùng
local nghĩa là một worker ghi file vào ổ riêng của nó, các worker khác không bao giờ
thấy, và không ai biết cho tới lúc bài đăng thiếu media.

> **Cân nhắc trước khi bật.** Media chính là nội dung seeding của bạn. Cả hệ thống này
> chạy local và fail-closed; đẩy file lên bucket bên thứ ba là đổi hẳn mức phơi bày. Nếu
> chỉ chạy một máy thì `local` vẫn là lựa chọn đúng.

---

## Seeding bằng bình luận

Seeding ngoài đời phần lớn là **bình luận** chứ không phải đăng lên tường mình: một tài
khoản mới lập mà tuần nào cũng đăng bài quảng cáo là mẫu hình dễ thấy, còn một tài khoản
để lại bình luận dưới bài người khác thì lẫn vào đám đông.

Mỗi nhóm trong chiến dịch chọn một trong hai:

| `post_kind` | `target` cần gì | Lấy nội dung từ |
| --- | --- | --- |
| `post` | Reddit: `{"subreddit": "..."}`; nền tảng khác: `{}` | `title` + `body` |
| `comment` | mọi nền tảng: `{"url": "https://..."}` | **chỉ** `body` |

Bình luận chỉ lấy `body`: `title` không có chỗ nào để đi trong một bình luận, nên hệ
thống từ chối ngay khi `body` rỗng thay vì lặng lẽ vứt nội dung bạn vừa soạn đi. Việc
từ chối xảy ra **trước khi mở trình duyệt** — một phiên Camoufox tốn ~400MB và vài chục
giây, báo lỗi cấu hình sau khi đã mở là lãng phí cả hai.

Xác nhận thành công cũng khác. Đăng bài thì chờ dấu hiệu của nền tảng ("Your post was
sent"); bình luận thì phần lớn nền tảng không báo gì cả, nên hệ thống chờ **chính đoạn
chữ vừa gõ** hiện ra trong trang. Cách đó không phụ thuộc ngôn ngữ giao diện.

---

## Chiến dịch lặp lại

`repeat=daily|weekly` sinh một **bản sao mới** mỗi kỳ chứ không đặt lại lịch cho chiến
dịch cũ. Đặt lại lịch thì lịch sử bị ghi đè — tuần này đăng được bao nhiêu, tuần trước
hỏng ở đâu, không còn dấu vết. Nhân bản giữ nguyên từng kỳ như một chiến dịch độc lập,
và `repeat_parent_id` nối cả chuỗi lại.

Một hệ quả cố ý: seed của biến thể là `(campaign_id, group_id, account_id)`. Bản sao có
id mới, nên tuần sau mỗi tài khoản viết một câu khác. Đúng thứ cần, vì đăng y hệt một
câu mỗi tuần là dấu vết rõ hơn cả việc đăng cùng giờ.

**Kỳ bị lỡ thì bỏ, không bù.** Worker chết một tuần rồi sống lại mà bù đủ bảy kỳ là bảy
chiến dịch cùng đến hạn một lúc — toàn bộ tài khoản đăng liên tục trong vài phút. Đó
đúng là mẫu hình mà cả hệ thống này tồn tại để tránh. Bỏ qua một ngày seeding không mất
gì; đăng bù cả tuần trong một buổi thì mất tài khoản.

Cùng lý do đó, bản sao lấy **giờ hiện tại** làm điểm bắt đầu khi mốc kỳ đã trôi qua.
Đặt `starts_at` vào quá khứ thì mọi job đều quá hạn ngay và cửa sổ rải mất tác dụng.

---

## Khung giờ thức theo nền tảng

Trước đây dùng chung 7h–23h cho tất cả. Giờ cao điểm của TikTok và Facebook khác hẳn
nhau, và một tài khoản hoạt động lệch hẳn với nhịp của nền tảng đó là một dấu vết — ít
rõ hơn fingerprint, nhưng vẫn là dấu vết.

Đặt **theo từng ngày trong tuần**, không phải một khung cho cả tuần: người thật không
thức dậy và đi ngủ đúng một khung giờ bảy ngày liền, nên dùng chung một khung cũng là một
mẫu hình — chỉ là kín đáo hơn giờ 3 giờ sáng.

Màn hình **Hours** có nút *all week* / *Mon–Fri* / *Sat–Sun* để đặt nhanh, và từng ngày
sửa riêng được. `PUT /windows` nhận `weekdays: [0..6]` (0 = thứ Hai, theo `date.weekday()`
của Python). Ngày nào không có bản ghi thì dùng mặc định trong `core/activity.py`.

Giờ kết thúc nhận **24 = nửa đêm**. Không có nó thì không diễn đạt được "hoạt động đến
nửa đêm", mà đó là khung giờ bình thường nhất của buổi tối — `time(24, 0)` không tồn tại
trong Python, nên `window_for()` trả về mốc thời gian chứ không trả về `time`.

Khung vắt qua nửa đêm sang ngày hôm sau thì không được hỗ trợ: giờ thức trải qua 3h sáng
chính là mẫu hình mà tính năng này sinh ra để tránh.

Khung này chi phối **hoạt động nền** — cuộn feed, đọc bài, thả cảm xúc. Giờ đăng bài đến
từ cửa sổ rải riêng của từng chiến dịch.

---

## Nhập tài khoản hàng loạt

Hai lửa, cố ý. `POST /accounts/import/check` đọc và kiểm **toàn bộ** file rồi trả về cả
dòng hợp lệ lẫn dòng hỏng kèm số dòng; chỉ khi bạn nhìn thấy kết quả và đồng ý thì
`POST /accounts/import` mới tạo. Nhập thẳng một file 200 dòng mà dòng 173 sai định dạng
thì 172 dòng trước đó đã nằm trong database và bạn không biết phải sửa từ đâu.

Cột bắt buộc `platform, handle`; tuỳ chọn `persona, daily_cap, start_warmup`; cột bí mật
`client_id, client_secret, username, password, totp_seed, recovery_email,
recovery_password` được mã hoá trước khi ghi xuống. Cột `cookie` đi vào cookie jar của
Profile chứ không vào vault của Account.

Định dạng của người bán acc — `username|password|hotmail|pass_hotmail|cookie` — nhập
được **nguyên xi**: dấu phân cách được đoán từ dòng tiêu đề (`|` là mặc định trên thực
tế, và bắt đổi sang dấu phẩy còn làm hỏng dữ liệu vì cookie có dấu phẩy bên trong), tên
cột của người bán được dịch qua `ALIASES`, và `username` đóng cả vai `handle` khi không
có cột `handle` nào. Nền tảng chọn một lần ở ngoài thay vì lặp lại 500 lần trong file.

Dòng có cookie được tạo luôn Profile kèm phiên đăng nhập, bỏ qua `login_profile.py`.
**Nhưng cookie hợp lệ về cú pháp không có nghĩa là nó còn sống**: nó được cấp cho một
thiết bị tại một địa chỉ, và dùng lại từ nơi khác chính là thứ nền tảng dùng cookie để
phát hiện. `core/cookies.py` kiểm phần kiểm được — thiếu cookie phiên thì báo ngay lúc
nhập, thay vì để lộ ra lúc đăng bài hỏng. Cột không đoán được thì **báo ra** chứ không lặng lẽ bỏ — gõ nhầm
`pasword` thì tài khoản được tạo mà không có mật khẩu, và bạn chỉ biết khi đăng nhập hỏng.

Bí mật không bao giờ đi ngược ra khỏi API: bản kiểm chỉ trả về **số lượng** trường bí mật
của mỗi dòng.

> **Một file CSV chứa mật khẩu là một file mật khẩu nằm trên ổ đĩa.** Xoá nó sau khi
> nhập xong. Giá trị được mã hoá trên đường vào, còn file bạn vừa tải lên thì không.

Tải file mẫu tại `GET /accounts/import/template`, hoặc nút trên màn hình Accounts.

---

## Báo ra ngoài khi có tài khoản kẹt

Acc kẹt lúc 2 giờ sáng thì nó nằm im tới khi bạn mở dashboard. Mỗi giờ nằm đó là một giờ
nền tảng nhìn thấy một tài khoản bị chặn mà không ai phản ứng.

Đặt `ALERT_WEBHOOK_URL` (và `ALERT_KIND=telegram|discord|slack|generic`) trong `.env`.
Ba nguyên tắc trong `core/alerts.py`:

- **Mỗi tài khoản kẹt chỉ báo MỘT lần.** Báo lại mỗi vòng quét là cách nhanh nhất để
  người ta tắt thông báo đi, rồi bỏ lỡ lần thật sự quan trọng.
- **Báo hỏng thì không được làm hỏng việc chính.** Webhook chết không được kéo theo cả
  vòng quét sức khoẻ, nên mọi lỗi ở đây đều bị nuốt và ghi log.
- **Không bao giờ đặt bí mật vào nội dung tin** — không mật khẩu, không mã 2FA, không
  cookie. Chỉ tên tài khoản, nền tảng, và lý do.

---

## Tài khoản sống được bao lâu

Câu hỏi duy nhất thực sự quan trọng khi vận hành seeding, và cũng là câu gần như không
ai đo. Người ta đổi proxy vì "nghe nói loại kia tốt hơn", kéo dài warm-up vì "cho chắc",
rồi không bao giờ biết thứ nào có tác dụng.

Màn hình **Survival** (`GET /analytics/survival`) cắt theo bốn cách: loại proxy, nhãn
proxy (đặt tên theo nhà cung cấp thì bảng này mới có ích), độ dài warm-up, và nhịp đăng.

Mỗi hàng mang `n` và `trustworthy`. Với 8 tài khoản một nhóm thì chênh lệch 60% và 75%
là nhiễu, không phải phát hiện — hàng dưới ngưỡng bị làm mờ ngay trên giao diện. Và đây
không phải thí nghiệm có đối chứng: tài khoản dùng proxy rẻ cũng thường là tài khoản bị
đẩy mạnh nhất, nên một khác biệt ở đây nói lên tương quan chứ không phải nguyên nhân.

---

## Phân trang

Năm danh sách dài đều trả về một **phong bì** thay vì một mảng trần:

```json
{ "items": [...], "total": 213, "limit": 50, "offset": 0 }
```

`GET /accounts`, `/profiles`, `/proxies`, `/campaigns`, `/content`. Mặc định 50 dòng,
trần cứng 500 — không phải để tiết kiệm băng thông, mà để một lần gõ nhầm `limit=100000`
không kéo cả database vào bộ nhớ rồi làm chết API.

`total` là số bản ghi **khớp điều kiện lọc**, không phải số dòng trong trang. Thiếu nó
thì giao diện không vẽ được "51–100 của 213", và người dùng không bao giờ biết mình đang
nhìn một phần hay toàn bộ. Đó là kiểu cắt bớt âm thầm mà việc này sinh ra để xoá bỏ:
trước đây `/campaigns` cắt cứng ở 100 và `/content` ở 200, **không nói gì cả** — một
chuỗi lặp hằng ngày vượt mốc 100 trong ba tháng, rồi các chiến dịch cũ lặng lẽ biến mất
khỏi màn hình.

Lọc ngay trong truy vấn, không lọc ở giao diện: `q` (tìm theo handle / nhãn / tiêu đề),
`platform`, `status`, `approved`, `alive`, `logged_in`. Tải hết về rồi lọc bằng
JavaScript nghĩa là kéo 200 bản ghi qua mạng để hiện ra 8 cái.

**Hàng đợi việc phải làm thì không phân trang** — một hàng đợi chỉ hiện trang đầu thì
không còn là hàng đợi, và những tài khoản ở trang hai sẽ không bao giờ được xử lý:

- `GET /accounts/without-profile` — tài khoản chưa có profile nên chưa đăng được gì.
  Tự loại Reddit (đi bằng API, không cần profile) và tài khoản đã chết.
- `GET /profiles?logged_in=false` — profile chưa từng đăng nhập tay.

Ô chọn tài khoản khi tạo chiến dịch cũng lọc ở server theo nền tảng và từ khoá, và **nói
rõ khi còn nữa** ("Showing 200 of 431") thay vi im lặng cắt mất phần dưới.

---

## Tương tác chéo giữa các tài khoản

Tính năng có ích nhất và nguy hiểm nhất trong hệ thống.

Có ích: một bài không có tương tác nào thì không lan được. Vài lượt thích đầu tiên là thứ
quyết định nền tảng có đẩy bài đi xa hay không.

Nguy hiểm: nó tạo ra một **đồ thị**. Và đồ thị hành vi mới là cách nền tảng bắt trại tài
khoản — dễ hơn nhiều so với fingerprint. Fingerprint hỏng thì mất một tài khoản; đồ thị
hỏng thì **mất cả cụm trong một lần quét**, vì một tài khoản bị gắn cờ dẫn ra tất cả
những tài khoản liên quan.

Bốn hình dạng lộ ra ngay lập tức, và `core/graph.py` không cho phép tạo ra chúng:

| Hình dạng | Luật chặn |
|---|---|
| Đồ thị dày — ai cũng theo dõi tất cả | `MAX_DENSITY = 0.15` (cộng đồng người thật: 0.01–0.10) |
| Đối xứng hoàn toàn | chỉ ~25% lượt theo dõi được đáp lại |
| Một tài khoản thành trung tâm | `MAX_INTERNAL_FOLLOWING = 12`, và ưu tiên acc đang theo dõi ít nhất |
| Đồng bộ — bài vừa lên đã có 12 lượt thích | tương tác bắt đầu sau ≥18 phút, rải trong nhiều giờ, và chỉ **một phần** người theo dõi |

Các luật nằm **trong hàm**, không phải tuỳ chọn. Một tuỳ chọn "cho phép đồ thị dày" chỉ
tồn tại để có người bật nó vào lúc ba giờ sáng.

**Mật độ chỉ được áp từ 10 tài khoản trở lên** (`MIN_ACCOUNTS_FOR_DENSITY`). Mật độ là
một tỷ lệ, và tỷ lệ thì vô nghĩa ở N nhỏ: với ba tài khoản, một cạnh duy nhất đã là 17% —
trên trần — trong khi một người theo dõi một người khác trong nhóm ba người là chuyện
không ai để ý. Dưới ngưỡng, luật là số tuyệt đối: trung bình một cạnh mỗi tài khoản.

Đồ thị **lớn lên từng ít một**: tối đa 8 cạnh mới mỗi ngày trên toàn hệ thống. Năm mươi
lượt theo dõi xuất hiện trong một buổi sáng là một sự kiện, không phải một mạng xã hội.

Reddit bị loại khỏi đồ thị: nó đi bằng API, không có profile trình duyệt và không có công
thức theo dõi. Lập cạnh cho nó là tạo ra việc không bao giờ làm được.

Một cạnh chỉ tính là **có thật** khi trình duyệt bấm được và **thấy nút đổi thành
Following**. Coi cạnh đã lập kế hoạch là đã xong thì mọi phép tính mật độ sau đó đều sai.

> **Thứ hệ thống không đo được, và nó nói thẳng ra trong `audit()`:** nó chỉ thấy cạnh
> giữa các tài khoản *của bạn*. Nó không biết mỗi tài khoản theo dõi bao nhiêu người thật
> bên ngoài — mà **tỷ lệ nội/ngoại mới là con số quan trọng nhất**. Một tài khoản theo dõi
> 8 tài khoản nội bộ và 300 người thật thì hoàn toàn bình thường; cùng 8 cạnh đó mà không
> theo dõi ai khác thì là một cái bẫy. Hai trường hợp giống hệt nhau trong database.

Xem trên màn hình **Network**, hoặc `GET /graph`.

---

## Điện thoại thật

Đường này **song song** với browser profile chứ không thay thế. Profile là một danh tính
*trình duyệt* (fingerprint + cookie jar); Device là một danh tính *thiết bị* (máy thật,
app thật).

Lý do tồn tại: app thật gửi lên những tín hiệu trình duyệt không có cách nào giả — cảm
biến, độ nghiêng, ID thiết bị, nhịp chạm màn hình. Giả lập mobile bằng cách đổi
user-agent trên trình duyệt desktop **không** cho bạn những tín hiệu đó. Nó cho bạn một
chuỗi chữ, kèm một fingerprint **tự mâu thuẫn** — UA khai là điện thoại trong khi WebGL
báo card đồ hoạ máy bàn. Cái đó dễ bị bắt hơn một profile desktop trung thực, không phải
khó hơn.

Bất biến giữ nguyên: **một acc ↔ một thiết bị ↔ một proxy, không xoay.** Chạy cùng một
acc lúc trên web lúc trên app từ hai IP khác nhau là dấu vết rõ hơn mọi thứ hệ thống này
đang tránh.

### iOS: không chạy được trên Windows

Không phải chuyện bỏ thêm công sức — đây là bức tường nền tảng:

- Tự động hoá app iOS bắt buộc phải build và **ký WebDriverAgent bằng Xcode**, mà Xcode
  chỉ chạy trên macOS.
- iOS Simulator **không cài được app từ App Store**, nên kể cả có macOS thì Simulator
  cũng không chạy được TikTok hay Facebook.

`DeviceOS.IOS` tồn tại trong mô hình dữ liệu vì nó chịu được, không phải vì chạy được.
Muốn iOS thật thì cần một máy Mac và iPhone thật.

### Cần gì cho Android

`GET /devices/preflight` liệt kê **tất cả** những thứ còn thiếu trong một lần, thay vì
báo thứ đầu tiên rồi dừng — với chuỗi công cụ Android, cài một thứ rồi chạy lại để gặp
thứ tiếp theo là cả buổi chiều.

1. **Android Platform Tools** (`adb`) trong PATH
2. **Appium Python client** — `pip install Appium-Python-Client`
3. Bật **USB debugging** trên máy, và bấm *cho phép* khi nó hỏi

*Scan for phones* (`POST /devices/sync`) đối soát máy đang cắm với database. Nó **không
tự thêm máy mới**: một cái điện thoại cắm vào để sạc cũng hiện ra trong `adb devices`.
Máy lạ được trả về trong `unknown` để bạn tự quyết.

Máy rút dây ra thì chuyển sang `offline` ngay. Để nguyên `ready` nghĩa là worker giao
việc cho một máy không còn ở đó, rồi job thất bại vì một lý do không liên quan gì đến lý
do thật.

**Chưa có:** phần điều khiển app (mở TikTok, gõ, bấm đăng) nằm ở `adapters/android.py`
và cần Appium chạy thật. Máy này chưa có adb lẫn Appium, nên **chưa dòng nào chạm vào
thiết bị thật** — y như `RECIPES` của trình duyệt.

---

## Workspace

Workspace giữ persona, persona giữ tài khoản. Chiến dịch, nội dung và túi hashtag cũng
thuộc về một workspace. **Proxy và thiết bị thì dùng chung** cho tất cả — chúng là hạ
tầng, không phải nội dung.

Có một **bộ chọn workspace trên thanh điều hướng**, và nó là thứ quyết định màn hình
Accounts hiển thị gì. Lựa chọn được nhớ trong `localStorage` nên không mất khi chuyển
trang.

Trước đây khái niệm này bị lộ ra một nửa và đó là một lỗi thật: ô *Workspace* trong form
tạo tài khoản **không điều khiển gì cả**. Nó nạp `/personas` — toàn bộ persona của mọi
workspace — nên chọn workspace nào thì danh sách persona vẫn y hệt, và chọn một persona
có sẵn sẽ lặng lẽ đặt tài khoản vào workspace **của persona đó** chứ không phải cái vừa
chọn. Giờ `/personas?workspace_id=` lọc thật, và danh sách nạp lại mỗi khi đổi workspace.

Màn hình **Workspaces** đổi tên và xoá được, kèm số persona / tài khoản / chiến dịch /
nội dung mỗi cái đang giữ. Xoá một workspace còn tài khoản bị **từ chối** trừ khi
`force=true`, và thông báo nói rõ cái mất là gì: xoá nó kéo theo persona, tài khoản,
profile, và **cookie jar bên trong** — thứ không khôi phục được, chỉ đăng nhập tay lại
từng cái một.

> Bộ test cũ để lại một workspace "Library test" sau **mỗi lần chạy**. Fixture giờ tự dọn
> (`yield` rồi `DELETE ?force=true`), và 6 cái tồn đọng đã được xoá.

---

## Chưa có

- **Hệ thống người dùng thật.** Xem mục Xác thực ở trên — một token dùng chung là đủ
  cho localhost, không đủ để đưa lên mạng.
- **Nút mở trình duyệt trên dashboard.** Trang web không có quyền khởi chạy tiến trình
  trên máy bạn, nên đăng nhập lần đầu và giải checkpoint vẫn qua lệnh CLI — dashboard
  hiện sẵn lệnh kèm nút chép.
- **noVNC.** Cơ chế trạng thái đã đầy đủ; `scripts/takeover.py open` mở trình duyệt
  ngay trên máy bạn. noVNC chỉ thêm đường truyền hình ảnh khi worker chạy trong
  container trên máy chủ — không đổi gì về trạng thái.
- **Thả cảm xúc thật.** `REACT` hiện chỉ cuộn và xem, cố ý chưa bấm.
- **Tự động đăng ký tài khoản.** Cố ý nằm ngoài phạm vi: nó cần vượt CAPTCHA và xác
  minh SMS bằng máy — luồng được canh gắt nhất — và tự động hoá nó là dựng công cụ
  gian lận đăng ký chứ không còn là vận hành tài khoản bạn kiểm soát. Đăng ký tay,
  rồi nhập vào bằng CSV hoặc màn hình Accounts.

**Chưa đo được:** tiêu chí thật của giai đoạn 02 và 03 là *tài khoản có trụ được 14 rồi
30 ngày không*, và *một bài có lên thật không*. Cả hai cần acc thật, proxy dân cư thật,
chạy trong thời gian thật. Phần máy móc đã xong; con số thì chỉ đo được khi bạn cắm dữ
liệu thật vào.

---

## Ghi chú vận hành

`VAULT_KEY` trong `.env` mã hoá toàn bộ cookie jar. **Mất khoá là mất hết phiên đăng
nhập, không khôi phục được.** Sao lưu nó riêng, đừng để chung với bản sao lưu DB.

Cổng Postgres và Redis đã đổi khác mặc định (5433 và 6380) để không đụng dịch vụ có sẵn.

Thư mục này nằm trong git repo `C:\Users\Admin`. Nếu muốn tách riêng thì `git init` ngay
tại đây trước khi commit.
