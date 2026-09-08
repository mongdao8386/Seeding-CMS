# Dựng lại từ đầu — kế hoạch từng phần

Quyết định ngày 08/09/2026: đập hệ thống cũ, dựng lại từng phần. Bản cũ giữ nguyên ở nhánh
`legacy` / tag `v0-legacy` trên GitHub — không mất gì, chỉ không phát triển tiếp.

## Vì sao đập, và đập cái gì

Giả định sai từ đầu: *trình duyệt Camoufox là đường chính cho mọi nền tảng.* Đo thật qua
proxy dân cư: trang web mất 90–300 giây, endpoint JSON mất 1–3 giây. Mọi thứ xây trên giả
định đó (adapter trình duyệt cho 5 nền tảng, selector viết mù, hoạt động nền cuộn feed) chưa
từng chạy được trên tài khoản thật.

Giao diện cũ: 11 trang, 3.300 dòng, bảng dày đặc, nhiều khái niệm (workspace, persona, hashtag
set, network, devices, analytics) mà người vận hành 7–100 tài khoản không cần nhìn mỗi ngày.

**Giữ lại nguyên vẹn** (đã chạy thật, có test): đăng TikTok bằng HTTP (~4 s), đọc For You,
signer (`tools/tiktok-signer`), governor + quiet period, khung giờ vàng, readiness, vault,
import acc/proxy theo định dạng người bán, cookie parser. **Dữ liệu trong DB giữ nguyên**:
14 tài khoản, 14 profile có cookie, 7 proxy, 28 biến thể nội dung, media.

## Nguyên tắc mới

1. **API là đường chính**, trình duyệt lùi về ba việc: đăng nhập lần đầu, tiếp quản checkpoint,
   nút "mở" để nhìn tận mắt.
2. **Mỗi nền tảng một gói** `platforms/<tên>/` gồm client, publish, warm, probe, health — và
   một *health check* riêng: nền tảng đổi API thì dashboard đỏ ngay.
3. **Giao diện theo việc, không theo bảng.** Ba câu hỏi của người vận hành mỗi sáng:
   *Acc nào còn sống? Hôm nay đăng gì? Cái gì đang cần tôi?* Mỗi câu một màn hình.
4. **Từng phần, mỗi phần dùng được ngay** và là một commit.

## Cấu trúc

```
src/seeding/
  domain/        models, bất biến (một acc – một profile – một proxy), vault
  scheduling/    khung giờ vàng, governor (ramp + quiet period), planner
  platforms/
    tiktok/      client.py  publish.py  warm.py  probe.py  health.py
    instagram/   (aiograpi)   — phần 5
    x/           (twifork)    — phần 6
  ops/           readiness, takeover, health sweep, alerts, import
  api/           routes mỏng, một file mỗi màn hình
  worker/        tick, run_post, run_warm, plan_day, health
web/             giao diện mới (Next.js), 5 màn hình
tools/tiktok-signer/
```

## Giao diện: 5 màn hình

| Màn hình | Trả lời | Nội dung |
|---|---|---|
| **Tổng quan** | Cái gì cần tôi? | Hàng đợi chờ người (nổi nhất), sức khoẻ đội (sống/chết/đang nuôi), hôm nay: đã đăng / sắp đăng / bị chặn |
| **Tài khoản** | Acc nào còn sống? | Danh sách gọn: handle, nền tảng, proxy, phiên, ngày nuôi, việc gần nhất. Dán acc/proxy để nhập. Bấm vào → chi tiết |
| **Chi tiết tài khoản** | Acc này đang làm gì? | Dòng thời gian: đăng, thả tim, follow, bình luận, checkpoint. Nút mở trình duyệt, đổi proxy, tạm dừng |
| **Nội dung & Lịch** | Hôm nay đăng gì? | Kho video/caption, chọn acc, lịch theo ngày với mốc giờ vàng; kéo thả |
| **Cài đặt** | — | Giờ vàng theo thứ, warm-up, nhịp, cảnh báo, signer |

Bỏ khỏi v1: workspace, persona riêng (gộp vào tài khoản), hashtag set, network graph, analytics,
devices. Thêm lại khi cần, không phải vì đã có.

## Các phần

| # | Phần | Kết quả dùng được |
|---|---|---|
| 0 | Khung: cấu trúc mới, DB giữ nguyên, launcher, signer, CI test | `Start.cmd` bật lên trống nhưng chạy |
| 1 | Tài khoản: nhập acc/proxy (dán), readiness, mở trình duyệt, cookie | Màn hình Tài khoản |
| 2 | Đăng TikTok: HTTP publish, khung giờ vàng, governor, quiet period | Màn hình Nội dung & Lịch, bài lên thật |
| 3 | Nuôi TikTok: For You, thả tim/follow/bình luận người lạ | Dòng thời gian trong Chi tiết tài khoản |
| 4 | Vận hành: hàng đợi chờ người, health, cảnh báo Telegram | Màn hình Tổng quan |
| 5 | Instagram qua aiograpi: đăng ảnh/Reel, nuôi từ Reels đề xuất, kiểm phiên HTTP | Tab Instagram dùng được y như TikTok |
| 6 | X qua twifork, health check theo GraphQL id | Đăng + nuôi X |
| 7 | Đổi username/tên/avatar theo lịch; chatbot (định nghĩa sau) | |

Mỗi phần: code + test + một đoạn trong `HUONG-DAN.md`, rồi commit.
