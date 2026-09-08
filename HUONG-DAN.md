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

## 4. Đăng bài đi đường nào

TikTok đăng bằng **HTTP** thẳng tới các endpoint của TikTok Studio (7 bước, ~4 giây) qua
proxy của acc, ký bằng signer ở `tools/tiktok-signer`. Không mở trình duyệt. Bước đăng
cuối không bao giờ tự thử lại — không rõ kết quả thì bài vào trạng thái **cần bạn**, vì
thử lại có thể đăng hai lần.

## 5. Khi có sự cố

- **Không gọi được API**: `Start.cmd` chưa chạy, hoặc cửa sổ "Seeding - API" báo lỗi.
- **Signer chưa sẵn sàng** (góc trái dưới): xem cửa sổ "Seeding - Signer". Cần Chrome hoặc
  Edge trên máy.
- **Acc "Thiếu proxy"**: dán thêm proxy.
- **Bài "cần bạn"**: bấm vào tài khoản, mở trình duyệt, xem bài đã lên chưa trước khi lên
  lịch lại.

Sinh token / khoá: `python scripts/gen_api_token.py`, `python scripts/gen_vault_key.py`.
