# Hướng dẫn vận hành

Bản mới, viết lại theo từng phần của `docs/REBUILD.md`. Bản cũ nằm ở nhánh `legacy`.

## 1. Bật lên

```
Start.cmd
```

Nó bật Postgres + Redis (Docker), API (cổng 8000), worker, signer (8080) và dashboard
(3000), rồi in `API_TOKEN` ra màn hình. Mở **http://localhost:3000**, dán token. Tắt bằng
`Stop.cmd`.

Điện thoại cùng wifi: `http://<IP máy>:3000` — giao diện có thanh dưới cho màn hẹp.

Cấu hình trong `.env` (chép từ `.env.example`). Ba giá trị hay chỉnh:

| | mặc định | nghĩa |
|---|---|---|
| `WARMUP_QUIET_DAYS` | 2 | mấy ngày đầu **không đăng gì**, chỉ nuôi |
| `WARMUP_DAYS` | 3 | ramp từ 1 bài/ngày lên trần trong mấy ngày |
| `DEFAULT_DAILY_CAP` | 3 | trần bài/ngày sau warm-up |

## 2. Tài khoản (phần 1)

Màn hình **Tài khoản** → **Dán tài khoản**: dán đúng file người bán, mỗi dòng

```
username|password|hotmail|pass_hotmail|cookie
```

(có hay không có dòng tiêu đề đều được; cookie TikTok có dấu `|` bên trong cũng được).
Nó kiểm trước — bao nhiêu dòng dùng được, bao nhiêu có phiên — rồi mới nhập. Dòng có
cookie thì tạo luôn profile đã đăng nhập.

**Dán proxy** trước hoặc sau đều được: `host:port:user:pass`, `user:pass@host:port`,
`host:port`. Mỗi proxy được thử ngay. Tài khoản có phiên sẽ tự gắn một proxy rảnh đã thử
OK — **một acc một proxy, không dùng chung, không đổi**. Hết proxy rảnh thì acc nằm ở
"Thiếu proxy" cho tới khi bạn dán thêm.

Bấm vào một tài khoản → **Mở trình duyệt**: cửa sổ thật với đúng proxy, cookie, fingerprint
của acc đó. Đăng nhập tay, giải captcha, xem gì cũng được; đóng cửa sổ là cookie được lưu.

## 3. Nội dung & Lịch (phần 2)

**Thêm bài**: kéo video vào, viết caption. Dùng `{a|b|c}` để mỗi tài khoản một câu khác
nhau — số biến thể hiện ngay dưới ô. Bài có video mới đăng được lên TikTok.

**Lên lịch**: chọn bài, chọn tài khoản (chỉ acc sẵn sàng được liệt kê), chọn ngày. Mỗi
acc một bài, bám vào **giờ vàng** gần nhất của nền tảng; nhiều acc cùng ngày thì rải qua
các mốc khác nhau, mỗi mốc lệch vài phút.

Lịch tuần: kéo thẻ bài sang ngày khác để dời — nó tự bám giờ vàng của ngày đó. Rê chuột
vào thẻ để huỷ. Thẻ xanh lá = đã lên (bấm "mở" xem trên TikTok); vàng = cần bạn hoặc hỏng.

Giờ vàng đặt ở **Cài đặt**: bật/tắt từng giờ cho từng thứ, từng nền tảng.

Hai ngày đầu của warm-up job vẫn nằm lịch nhưng worker **không đăng** — nó lùi bài tới
giờ vàng đầu tiên sau khi hết ngày im lặng. Đây là cố ý.

## 3b. Nuôi tài khoản (phần 3)

Không phải bật gì. Mỗi sáng (và lúc `Start.cmd` khởi động) worker đọc **For You của
chính từng tài khoản** qua proxy của nó, chọn vài video đang lên của người lạ, rồi rải
trong ngày: 4–8 thả tim, 1–3 follow creator, 0–2 bình luận (ngày đầu một nửa, không bình
luận). Bình luận chỉ vào video đã thả tim, sau ít nhất 8 phút, câu lấy từ bộ tiếng Việt
đời thường trong `platforms/tiktok/interact.py`.

Nhìn ở đâu: **Tổng quan** có dòng "hôm nay: x/y thả tim · follow · bình luận"; bấm vào một
tài khoản thấy **dòng thời gian** — đăng bài và từng lần thả tim / follow / bình luận,
cái nào xong, cái nào hỏng.

Tắt bằng `TIKTOK_INTERACT_VIA_HTTP=false`. Thả tim và follow được thử lại khi không rõ
kết quả; bình luận thì không — vào "cần bạn".

## 3c. Khi hệ thống dừng lại chờ bạn (phần 4)

Gặp checkpoint, captcha, phiên chết hay bài đăng không rõ kết quả thì hệ thống **dừng
tài khoản đó lại** và đưa vào hàng đợi **Cần bạn** ở đầu màn hình Tổng quan. Không tự
thử lại, không tự đăng nhập lại — hai việc đó là cách nhanh nhất để mất acc.

Mỗi dòng trong hàng đợi có: lý do, và bốn nút.

- **Mở trình duyệt** — mở đúng profile, đúng proxy, bạn tự giải trên trang thật.
- **Mã 2FA** — nếu acc có lưu `totp_seed` khi dán.
- **Đã giải** — acc về trạng thái *đang nuôi* (đi chậm lại một nhịp, không về "hoạt động"
  ngay). Bài bị kẹt được hẹn lại **6 tiếng sau**, không đăng liền.
- **Bỏ tài khoản** — acc chuyển sang *chết*, không chạy gì nữa.

Worker tự **kiểm phiên** mỗi giờ (mỗi lần tối đa 10 profile quá hạn 12 tiếng): gọi một
endpoint nhẹ bằng cookie của acc qua proxy của nó. Hỏng 2 lần liên tiếp thì vào hàng đợi.
Kết quả kiểm hiện trong dòng thời gian của tài khoản ("Kiểm phiên: còn sống / hỏng").

Cảnh báo ra ngoài: đặt `ALERT_WEBHOOK_URL` (Telegram, Discord, Slack hay webhook bất kỳ)
và `ALERT_KIND` trong `.env`. Mỗi yêu cầu chờ người báo **một lần**, không báo lại mỗi
vòng quét. Bấm **Gửi thử** ở Cài đặt để chắc là tin đến.

## 3d. Instagram (phần 5)

Không mở trình duyệt. Instagram đi bằng **API riêng của app** (thư viện aiograpi) với
cookie `sessionid` của tài khoản, qua proxy của profile. Dán tài khoản Instagram y như
TikTok: cột `platform` = `instagram`, cột cookie có `sessionid`.

- **Đăng bài**: ảnh lên thành bài thường, video (`.mp4`, `.mov`) lên thành **Reel**.
  Tiêu đề + thân bài thành caption. Không đăng được bài chỉ có chữ.
- **Nuôi**: cùng nhịp với TikTok (thả tim 4–8, follow 1–3, bình luận 0–2 mỗi ngày), dích
  lấy từ Reels mà Instagram đề xuất cho chính tài khoản đó. Giờ vàng chỉnh ở tab
  Instagram trong Cài đặt.
- **Kiểm phiên**: một request nhẹ qua proxy, không mở trình duyệt.
- **Thiết bị**: lần đầu chạy, mỗi profile được sinh một bộ thiết bị (uuid, model, UA,
  vi_VN, múi giờ VN) và giữ cố định về sau — đổi thiết bị mỗi lần gọi là dấu vết rõ nhất.

Instagram từ chối thế nào thì xử lý thế ấy: checkpoint / challenge / phiên chết → **Cần
bạn**; "please wait a few minutes" hoặc action blocked → nghỉ rồi thử lại; tài khoản bị
khoá hẳn → *chết*. Đăng bài không rõ kết quả (mạng đứt giữa chừng) → **Cần bạn**, không
tự đăng lại — có thể bài đã lên.

Tắt bằng `INSTAGRAM_ENABLED=false`.

## 3e. X (phần 6)

Không mở trình duyệt. X đi bằng API nội bộ của trang web qua thư viện **twifork** (fork
còn bảo trì của twikit), với hai cookie `auth_token` và `ct0`, qua proxy của profile.
Dán tài khoản với `platform` = `x`; cột cookie phải có **cả hai** cookie đó.

- **Đăng bài**: chữ không, hoặc chữ kèm một ảnh / video / gif. Quá 280 ký tự thì cắt ở
  ranh giới từ và thêm dấu ba chấm.
- **Nuôi**: thả tim, follow, trả lời — cùng nhịp với TikTok và Instagram, đích lấy từ
  For You của chính tài khoản. Trả lời được ghép thêm một đuôi nhỏ (emoji, dấu chấm) để
  X không chặn vì trùng chữ.
- **Kiểm phiên**: một request nhẹ qua proxy.

**Thư viện X lệch.** X đổi mã (query id) của các API nội bộ vài tuần một lần. Khi đó
*mọi* job X hỏng cùng lúc — đó không phải lỗi tài khoản, và hệ thống không ghi nó lên
tài khoản: Cài đặt hiện "Thư viện X lệch", cảnh báo gửi ra ngoài **một lần mỗi 12
tiếng**, job X được hẹn lại chứ không vào "Cần bạn". Sửa:

```
.venv\Scripts\pip install -U twifork
```

rồi bật lại worker. Nếu bản mới nhất vẫn lệch, chờ tác giả twifork vá (thường trong
vài ngày) hoặc tắt X bằng `X_ENABLED=false` cho tới lúc đó.

## 4. Đăng bài đi đường nào

TikTok đăng bằng **HTTP** thẳng tới các endpoint của TikTok Studio (7 bước, ~4 giây) qua
proxy của acc, ký bằng signer ở `tools/tiktok-signer`. Instagram đăng qua API của app
(aiograpi), X qua API nội bộ của web (twifork). Không cái nào mở trình duyệt. Bước đăng cuối không bao giờ tự thử lại — không
rõ kết quả thì bài vào trạng thái **cần bạn**, vì thử lại có thể đăng hai lần.

## 5. Khi có sự cố

- **Không gọi được API**: `Start.cmd` chưa chạy, hoặc cửa sổ "Seeding - API" báo lỗi.
- **Signer chưa sẵn sàng** (góc trái dưới): xem cửa sổ "Seeding - Signer". Cần Chrome hoặc
  Edge trên máy.
- **Acc "Thiếu proxy"**: dán thêm proxy.
- **Bài "cần bạn"**: hàng đợi ở Tổng quan (mục 3c). Với bài đăng không rõ kết quả, mở
  trình duyệt xem bài đã lên chưa rồi mới bấm "Đã giải".

Sinh token / khoá: `python scripts/gen_api_token.py`, `python scripts/gen_vault_key.py`.
