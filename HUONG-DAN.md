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

## 2c. Đăng nhập lại một acc (phiên chết, captcha)

Khi hàng chờ người báo "phiên chết" hay "captcha":

1. Trên thẻ đó bấm **Mở trình duyệt**. Cửa sổ mở với đúng proxy, fingerprint và cookie
   của acc (qua proxy dân cư có thể mất vài phút mới hiện trang).
2. Đăng nhập lại ngay trong cửa sổ đó: mật khẩu, hoặc **quét mã QR** bằng app TikTok
   đang đăng nhập trên điện thoại (khi chỉ có cookie mà không có mật khẩu). Gặp captcha
   thì giải luôn. Mã 2FA lấy ở nút **Mã 2FA** nếu đã lưu totp.
3. **Đóng cửa sổ.** Cookie mới được lưu; hệ thống hỏi TikTok ngay xem phiên mới có sống
   không và ghi vào dòng thời gian ("Kiểm phiên").
4. Bấm **Đã giải**. Nếu phiên vẫn chết, nút này từ chối và nói rõ; làm lại bước 1–3.

Vì sao phải đăng nhập *trong profile* chứ không dán cookie mới: phiên sinh ra ở đúng
thiết bị (fingerprint + proxy) thì TikTok mới tin những cú bấm sau đó. Cookie dán từ
máy khác là lý do gặp captcha ngay lần thả tim đầu tiên (mục 3b).

## 2b. Hai loại tài khoản: xây kênh và tương tác chéo (phần 11)

- **Xây kênh** (mặc định): đăng bài, nuôi hướng ra ngoài (For You + từ khoá), chatbot,
  đổi danh tính — và **được đội tương tác chéo đẩy**.
- **Tương tác chéo** (booster): chỉ thả tim / follow / bình luận sticker / đăng lại vào
  **bài của tài khoản xây kênh**. Không đăng bài, không nuôi ra ngoài, không chatbot.
  **Không cần proxy** — đây là lựa chọn có chủ ý của bạn: cả nghìn acc đi từ một IP là
  dấu vết rõ, nên đội này nên nằm trên máy/mạng khác với đội xây kênh.

Chọn loại khi **Dán tài khoản** (nút "Xây kênh / Tương tác chéo" trên hộp dán, hoặc cột
`role` trong file: `channel` | `booster`, nhận cả tiếng Việt "tương tác chéo"). Đổi sau
ở Chi tiết tài khoản. Màn Tài khoản lọc được theo loại; Tổng quan đếm riêng.

Nhịp của booster mỗi ngày: thả tim 2–5 bài (xem 30–45 giây mỗi bài), follow 1–2 kênh
chưa follow, bình luận sticker 0–1, đăng lại 0–1 (từ ngày thứ 2). Bài chọn từ những lần
đăng đã lên trong 7 ngày, ưu tiên bài mới, **mỗi bài mỗi ngày nhận tối đa
`BOOST_PER_POST_CAP` (30) lượt tim từ đội booster** — nghìn acc dồn vào một bài trong
một giờ là cách nhanh nhất để bài bị bóp. Lịch rải trong khung giờ thức của nền tảng,
mỗi booster một giờ khác nhau. Việc bấm dùng đúng đường của nền tảng (TikTok: trình
duyệt, mở video thật; IG/X/Reddit: API).

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

**Xem trước, bấm sau.** Mỗi lần thả tim, worker mở trang video rồi **chờ 30–45 giây** mới
bấm tim; follow thì mở trang cá nhân, xem 10–20 giây; bình luận mở lại video, 20–40 giây
rồi mới gõ; đăng lại xem 30–45 giây. Không có gì được bấm ngay giây đầu tiên sau khi đọc
feed — đó là nhịp của máy. Thời gian xem nằm trong từng job (`duration_seconds`), nhìn
được ở dòng thời gian.

**TikTok bấm bằng trình duyệt.** Đo thật 08/09/2026: đọc feed / tìm kiếm / chi tiết video
qua HTTP chạy 1–3 giây và tốt, nhưng **cổng ghi** (thả tim, follow, bình luận) trả 200
rỗng cho mọi biến thể HTTP — kể cả với CSRF token thật và msToken TikTok vừa cấp. Nên
chọn đích và lập lịch vẫn HTTP, còn bấm thì mở đúng trang video trong Camoufox với
profile + proxy của acc: trang tự phát video, TikTok thật sự thấy 30–45 giây xem, rồi
mới bấm. Chậm (mỗi trang 1,5–8 phút qua proxy dân cư) nhưng là đường duy nhất đã lên
được. Cửa sổ chờ trang là 8 phút (5 phút thất bại hai lần), worker giữ mỗi job tới 15
phút, mỗi acc chỉ mở một trình duyệt một lúc. `TIKTOK_ACTIONS=http` để quay lại đường
HTTP nếu TikTok mở cổng.

**"Đã thích" trên giao diện không phải bằng chứng.** Đo 08/09/2026: acc P03 có phiên đã
chết (TikTok trả `session_expired`) mà trang video vẫn hiện nút tim, bấm vẫn chuyển sang
"đã thích" — TikTok chỉ không lưu. Vì thế hệ thống hỏi TikTok trước mỗi hành động
(`passport/web/account/info`, 2 giây, qua proxy của acc): phiên chết thì job vào hàng
chờ người với lý do "logged_out", không tốn 8 phút trình duyệt. Quét sức khoẻ TikTok
cũng dùng đường này thay vì mở trình duyệt; kết quả hiện ở dòng thời gian của acc,
mục "Kiểm phiên".

**Cookie nhập từ máy khác thì TikTok không tin cú bấm.** Cùng ngày, trên acc P05 (phiên
sống, cookie nhập từ file): mở trang chủ thấy đang đăng nhập, xem video 42 giây, bấm
tim → TikTok đè **hộp captcha** lên nút. Acc HA1 bấm tim "thành công" lúc 17:27 thì
5 phút sau phiên chết. Nghĩa là phiên sinh ra ở thiết bị khác, còn cú bấm đến từ
fingerprint của profile Camoufox — TikTok đòi xác minh hoặc đăng xuất. Cách xử lý đúng
là qua **hàng chờ người**: job gặp captcha tự mở yêu cầu tiếp quản, người vận hành mở
trình duyệt của profile, giải captcha (hoặc đăng nhập lại ngay trong profile đó), từ
đó thiết bị được TikTok tin và các lần bấm sau mới có giá trị. Đọc lại phiên đã chết
qua HTTP là cách rẻ nhất để biết acc nào cần đăng nhập lại.

**Proxy phải tải được web TikTok.** Đo 08/09/2026: proxy HA1 không bao giờ hiện trang video
(53 file JS trên `ttwstatic.com` bị huỷ, trang trống 5 phút, cả khi mở cửa sổ). Hai lượt
đo cùng ngày, cửa sổ 4 phút: P02 không lần nào; P01, P04, P05, P06 mỗi proxy một lần
được (131 / 151 / 175 / 216 s) một lần không; P03 109–222 s, là proxy ổn nhất. Nghĩa là
proxy dân cư này "lúc được lúc không" quanh mốc 2–4 phút, nên cửa sổ chờ 8 phút là bắt
buộc, và mỗi job thả tim nên tính là có thể phải thử lại một lần. Đo lại bằng
`python scripts/check_proxy_tiktok.py P03 P04` mỗi khi thêm proxy mới. Acc trên proxy
nào không tải nổi trang thì job thả tim báo "page never rendered" và thử lại — đổi
proxy cho acc đó. `BROWSER_STATIC_BYPASS` (cho CDN tĩnh đi
thẳng) đã thử: TikTok trả trang "Không thể mở trang", nên để trống.

**Đăng lại (repost)**: 0–1 lần/ngày, chỉ từ ngày thứ 2 của warm-up, chỉ video đã thả
tim, xem lại 30–45 giây, sau thả tim ít nhất 3 phút, và không trùng video đã bình luận.
TikTok đi qua endpoint Repost của trang web (**chưa kiểm chứng trên acc thật**), X là
retweet; Instagram và Reddit không có repost.

**Đích lấy từ đâu.** Feed của chính acc, **cộng tìm kiếm theo từ khoá**: đặt
`WARM_KEYWORDS=làm đẹp, du lịch, ẩm thực` trong `.env` (và/hoặc chủ đề của persona). Mỗi
lần lập lịch chọn ngẫu nhiên 1–2 từ khoá, trộn kết quả tìm với feed, bỏ trùng, rồi mới
rải lịch. TikTok tìm qua trang tìm kiếm, Instagram theo hashtag, X theo search, Reddit
theo r/all. Không có từ khoá thì chỉ lấy từ feed.

**Bình luận khi nuôi chỉ là sticker** (`WARM_COMMENT_STYLE=sticker`, mặc định): TikTok
dùng sticker riêng của TikTok (`[loveface]`, `[laughwithtears]`…), nền tảng khác dùng
emoji; 1–3 cái, không chữ. Muốn câu chữ: `text`; trộn: `mixed`. Chatbot trả lời bình
luận dưới bài của mình vẫn dùng chữ — đó là trả lời người, không phải nuôi.

Nhìn ở đâu: **Tổng quan** có dòng "hôm nay: x/y thả tim · follow · bình luận"; bấm vào một
tài khoản thấy **dòng thời gian** — đăng bài và từng lần thả tim / follow / bình luận /
đăng lại, cái nào xong, cái nào hỏng.

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

## 3f. Đổi tên, username, ảnh đại diện (phần 7)

Một lô tài khoản mua về thường mang tên kiểu `user8827361` và ảnh trống. Vào **Chi tiết
tài khoản → Đổi danh tính**: gõ hoặc bấm gợi ý (tên Việt bình thường, username kiểu
người thật đặt), chọn ảnh từ thư viện, bấm **Đổi trong vài phút**. Worker làm sau 1–5
phút, kết quả hiện trên dòng thời gian; username mới thay luôn handle trong CMS.

- Ảnh đại diện: mỗi tài khoản nhận **một bản riêng** từ ảnh gốc (cắt lệch, đôi khi lật,
  chỉnh sáng nhẹ) — hai acc dùng cùng ảnh không ra hai file giống hệt.
- Username có luật của từng nền tảng và **thời gian chờ**: Instagram 14 ngày, X đổi thoải
  mái (CMS vẫn giữ 1 ngày), TikTok 30 ngày. Tên hiển thị và ảnh không giới hạn.
- **Instagram** và **X** đổi tự động. **TikTok chưa**: web TikTok không lộ endpoint sửa hồ
  sơ, còn trang sửa hồ sơ qua proxy dân cư mất nhiều phút — bấm *Mở trình duyệt*, vào
  *Sửa hồ sơ* làm tay.
- Đang có một lần đổi chờ chạy thì không hẹn thêm; huỷ được khi chưa chạy.

**Chatbot** trong kế hoạch chưa có định nghĩa (trả lời bình luận? nhắn tin? trò chuyện
với người vận hành?) nên chưa làm — cần nói rõ muốn gì trước.

## 3g. Bài đã đăng: xoá, sửa (phần 8)

Cuối màn hình **Nội dung & Lịch** có mục **Đã đăng**: mọi bài đã lên (link mở bài, ai
đăng, lúc nào). Mỗi bài có hai nút, worker làm trong 1–2 phút qua proxy của acc, kết quả
lên dòng thời gian của tài khoản:

- **Xoá trên nền tảng** — TikTok, Instagram, X, Reddit. Bài không mất khỏi CMS, chỉ đánh
  dấu *đã xoá* (bật "hiện cả bài đã xoá" để xem lại).
- **Sửa chú thích** — Instagram, Reddit. TikTok web không có đường sửa, X chỉ cho tài
  khoản trả phí: nút mờ đi kèm lý do, mở trình duyệt làm tay.

Facebook chưa có cả hai — mở trình duyệt làm tay.

## 3h. Reddit và Facebook (phần 9)

**Reddit** đi bằng API chính thức, không cần trình duyệt. Mỗi tài khoản tự tạo một
*script app* tại reddit.com/prefs/apps rồi dán cùng lúc với tài khoản: cột `client_id`,
`client_secret`, `username`, `password` (mẫu dán có sẵn các cột này). Có proxy gắn với
profile thì đi qua proxy, không thì đi thẳng.

- Đăng bài: chữ, ảnh hoặc video vào **một subreddit** — ô Subreddit hiện ra trong hộp
  Lên lịch khi chọn tab Reddit. Không điền thì không lên lịch được.
- Nuôi: upvote, "friend" (Reddit không có follow đúng nghĩa), bình luận — đích lấy từ
  front page của chính tài khoản, ngưỡng "đang lên" tính bằng điểm.
- Bài đã đăng: xoá và sửa đều được.

**Facebook** chỉ có một đường: trình duyệt thật (Camoufox) với profile + proxy của acc,
như bản cũ. Chậm (trang nặng qua proxy) và dễ gãy khi Facebook đổi giao diện — khi đó
job báo rõ "Could not find … update the recipe" chứ không đổ lên tài khoản.

- Đăng bài chữ hoặc chữ kèm ảnh; bình luận vào bài theo link.
- Thả tim / follow / bình luận theo lịch làm được, nhưng **không có nuôi tự động**: đọc
  feed bằng trình duyệt để chọn đích là quá nặng. Nuôi Facebook bằng tay qua *Mở trình
  duyệt*.
- Xoá / sửa bài, đổi danh tính: làm tay.

Tắt bằng `REDDIT_ENABLED=false`, `FACEBOOK_ENABLED=false`.

## 3i. Chatbot: tự trả lời bình luận và tin nhắn (phần 10)

**Tắt mặc định** — nó gửi chữ thật ra ngoài. Bật bằng `CHATBOT_ENABLED=true` trong `.env`.

Mỗi 10 phút (`CHATBOT_INTERVAL_MINUTES`), worker mở từng tài khoản đang chạy, đọc bình
luận dưới **bài của chính acc** (TikTok, Instagram, X, Reddit) và hộp thư chưa đọc
(Instagram, X — TikTok và Reddit không làm được tin nhắn), rồi trả lời. Kết quả hiện trên
dòng thời gian của tài khoản ("Trả lời bình luận", "Nhắn tin"), Tổng quan đếm theo ngày,
Cài đặt có thẻ Chatbot với lần chạy gần nhất.

Câu trả lời viết bằng:

- **Claude** (Anthropic API) khi có `ANTHROPIC_API_KEY` — theo giọng và chủ đề của persona
  (Tài khoản → persona: tên, giọng, chủ đề). Model mặc định `claude-sonnet-5`, đổi bằng
  `CHATBOT_MODEL`. Rẻ: mỗi câu ~100 token.
- **Bộ câu mẫu** tiếng Việt khi không có key — chạy được nhưng nhìn "máy" hơn.

Luật, áp cho cả hai: ngắn (1–2 câu), tiếng Việt đời thường, không link, không hashtag,
**không bao giờ tự nhận là bot**; spam / quảng cáo / thù ghét thì **im**. Tối đa
`CHATBOT_MAX_PER_HOUR` (8) câu mỗi giờ mỗi tài khoản, chỉ trả lời `CHATBOT_REPLY_RATIO`
(80%) bình luận, bỏ qua bình luận cũ hơn `CHATBOT_LOOKBACK_HOURS` (48), nghỉ 3–10 giây
giữa hai câu, không trả lời chính mình, không trả lời cuộc mà tin cuối là của mình, và
**không bao giờ trả lời hai lần** cùng một bình luận / tin nhắn (khoá theo URL, giữ 30 ngày).

Gặp checkpoint / phiên chết giữa chừng → tài khoản vào **Cần bạn**, chatbot dừng acc đó.
Key Claude sai hay hết quota → dừng lượt đó, ghi ở thẻ Chatbot, không đổ lên tài khoản.

Tắt riêng: `CHATBOT_COMMENTS=false` (bình luận), `CHATBOT_DMS=false` (tin nhắn).

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
