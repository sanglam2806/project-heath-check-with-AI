"""
Minimal backend i18n for static, user-facing validation/connection/
confirmation text (English + Japanese + Vietnamese). Deliberately does NOT
cover the LLM-generated evaluation content (TicketResult.missing_parts/
suggestions/notes from evaluator.py, or the Layer-1/Layer-3 generated
strings in git_scan.py) -- that's dynamic AI output written in English per
its prompt, a different concern from translating fixed strings.

TranslatableError is the base for every user-facing error raised anywhere
in the backend: it carries a message key, optional interpolation kwargs,
and the HTTP status code to respond with. main.py registers one global
FastAPI exception handler for it, so individual endpoints just raise the
error and never need to know the caller's language themselves.
"""
from typing import Dict, Optional

SUPPORTED_LANGUAGES = {"en", "ja", "vi"}
DEFAULT_LANGUAGE = "en"

MESSAGES: Dict[str, Dict[str, str]] = {
    # --- auth.py / main.py auth flow ---
    "auth.fields_required": {
        "en": "Name, email, and password are required.",
        "ja": "名前、メールアドレス、パスワードをすべて入力してください。",
        "vi": "Vui lòng nhập đầy đủ tên, email và mật khẩu.",
    },
    "auth.email_already_registered": {
        "en": "Email already registered.",
        "ja": "このメールアドレスはすでに登録されています。",
        "vi": "Email đã được đăng ký.",
    },
    "auth.invalid_credentials": {
        "en": "Invalid email or password.",
        "ja": "メールアドレスまたはパスワードが正しくありません。",
        "vi": "Email hoặc mật khẩu không đúng.",
    },
    "auth.not_authenticated": {
        "en": "Not authenticated.",
        "ja": "認証されていません。",
        "vi": "Chưa xác thực.",
    },
    "auth.invalid_or_expired_token": {
        "en": "Invalid or expired token.",
        "ja": "トークンが無効か、期限切れです。",
        "vi": "Token không hợp lệ hoặc đã hết hạn.",
    },
    "auth.user_not_found": {
        "en": "User not found.",
        "ja": "ユーザーが見つかりません。",
        "vi": "Không tìm thấy người dùng.",
    },

    # --- groups.py ---
    "groups.name_required": {
        "en": "Group name is required.",
        "ja": "グループ名を入力してください。",
        "vi": "Vui lòng nhập tên nhóm.",
    },
    "groups.name_exists": {
        "en": 'A group named "{name}" already exists.',
        "ja": "「{name}」という名前のグループはすでに存在します。",
        "vi": 'Nhóm có tên "{name}" đã tồn tại.',
    },
    "groups.not_found": {
        "en": "Group not found: {group_id}",
        "ja": "グループが見つかりません: {group_id}",
        "vi": "Không tìm thấy nhóm: {group_id}",
    },

    # --- projects.py ---
    "projects.name_required": {
        "en": "Project name is required.",
        "ja": "プロジェクト名を入力してください。",
        "vi": "Vui lòng nhập tên dự án.",
    },

    # --- main.py direct ---
    "main.project_forbidden": {
        "en": "You do not have permission to view this project.",
        "ja": "このプロジェクトを閲覧する権限がありません。",
        "vi": "Bạn không có quyền xem dự án này.",
    },
    "main.member_management_forbidden": {
        "en": "Only Owner/Admin roles can manage members.",
        "ja": "メンバーを管理できるのは Owner/Admin ロールのみです。",
        "vi": "Chỉ vai trò Owner/Admin mới có thể quản lý thành viên.",
    },
    "main.check_health_forbidden": {
        "en": "Only Owner/Admin/Editor roles can run a project health check.",
        "ja": "プロジェクトのヘルスチェックを実行できるのは Owner/Admin/Editor ロールのみです。",
        "vi": "Chỉ vai trò Owner/Admin/Editor mới có thể chạy kiểm tra sức khỏe dự án.",
    },
    "main.invite_not_found": {
        "en": "Invite not found, expired, or already used.",
        "ja": "招待が見つからないか、期限切れ、またはすでに使用されています。",
        "vi": "Không tìm thấy lời mời, đã hết hạn, hoặc đã được sử dụng.",
    },
    "main.no_jira_tickets": {
        "en": "No tickets found in this Jira project.",
        "ja": "この Jira プロジェクトにチケットが見つかりません。",
        "vi": "Không tìm thấy ticket nào trong dự án Jira này.",
    },
    "main.email_already_active": {
        "en": "This email already has an active account.",
        "ja": "このメールアドレスはすでにアクティブなアカウントを持っています。",
        "vi": "Email này đã có tài khoản đang hoạt động.",
    },
    "main.invite_email_sent": {
        "en": "Invite email sent.",
        "ja": "招待メールを送信しました。",
        "vi": "Đã gửi email mời.",
    },
    "main.invite_smtp_not_configured": {
        "en": "SMTP is not configured — copy this link and send it manually.",
        "ja": "SMTP が設定されていません。このリンクをコピーして手動で送信してください。",
        "vi": "SMTP chưa được cấu hình — hãy sao chép liên kết này và gửi thủ công.",
    },
    "main.jira_connected": {
        "en": "Connected successfully — found {count} ticket(s) in project {project_key}.",
        "ja": "接続に成功しました — プロジェクト {project_key} で {count} 件のチケットが見つかりました。",
        "vi": "Kết nối thành công — tìm thấy {count} ticket trong dự án {project_key}.",
    },
    "main.git_connected": {
        "en": 'Connected successfully — branch "{branch}" @ {commit_sha}.',
        "ja": "接続に成功しました — ブランチ「{branch}」@ {commit_sha}。",
        "vi": 'Kết nối thành công — nhánh "{branch}" @ {commit_sha}.',
    },
    "main.no_file_provided": {
        "en": "No file provided.",
        "ja": "ファイルが指定されていません。",
        "vi": "Chưa cung cấp file.",
    },
    "main.invalid_mapping_json": {
        "en": "Invalid mapping JSON.",
        "ja": "マッピングの JSON が不正です。",
        "vi": "JSON ánh xạ không hợp lệ.",
    },

    # --- jira_client.py ---
    "jira.site_url_required": {
        "en": "Jira Site URL is required.",
        "ja": "Jira サイト URL を入力してください。",
        "vi": "Vui lòng nhập Jira Site URL.",
    },
    "jira.email_token_required": {
        "en": "Username/Email and Password/API Token are required.",
        "ja": "ユーザー名またはメールアドレス、およびパスワードまたは API トークンを入力してください。",
        "vi": "Vui lòng nhập Username/Email và Password/API Token.",
    },
    "jira.wrong_credentials": {
        "en": "Wrong username/email or password/API token.",
        "ja": "ユーザー名/メールアドレス、またはパスワード/API トークンが正しくありません。",
        "vi": "Sai username/email hoặc password/API token.",
    },
    "jira.project_or_url_invalid": {
        "en": "Project not found or the Jira URL is incorrect.",
        "ja": "プロジェクトが見つからないか、Jira の URL が正しくありません。",
        "vi": "Không tìm thấy dự án hoặc URL Jira không đúng.",
    },
    "jira.host_error": {
        "en": "Jira returned an error (HTTP {code}).",
        "ja": "Jira がエラーを返しました（HTTP {code}）。",
        "vi": "Jira trả về lỗi (HTTP {code}).",
    },
    "jira.connect_failed": {
        "en": "Could not connect to Jira: {reason}",
        "ja": "Jira に接続できませんでした: {reason}",
        "vi": "Không thể kết nối tới Jira: {reason}",
    },
    "jira.timeout": {
        "en": "Connection to Jira timed out.",
        "ja": "Jira への接続がタイムアウトしました。",
        "vi": "Kết nối tới Jira đã hết thời gian chờ.",
    },
    "jira.invalid_json": {
        "en": "Invalid response from Jira (not JSON).",
        "ja": "Jira からの応答が不正です（JSON 形式ではありません）。",
        "vi": "Phản hồi từ Jira không hợp lệ (không phải JSON).",
    },
    "jira.project_key_required": {
        "en": "Project Key is required.",
        "ja": "プロジェクトキーを入力してください。",
        "vi": "Vui lòng nhập Project Key.",
    },
    "jira.missing_total": {
        "en": "Jira response is missing the total ticket count.",
        "ja": "Jira の応答にチケットの合計数が含まれていません。",
        "vi": "Phản hồi từ Jira thiếu tổng số ticket.",
    },

    # --- git_client.py ---
    "git.url_required": {
        "en": "Repository URL is required.",
        "ja": "リポジトリ URL を入力してください。",
        "vi": "Vui lòng nhập Repository URL.",
    },
    "git.http_only": {
        "en": "Only HTTP(S) Git URLs are supported, e.g. https://github.com/org/repo.git",
        "ja": "HTTP(S) の Git URL のみサポートしています（例: https://github.com/org/repo.git）。",
        "vi": "Chỉ hỗ trợ URL Git dạng HTTP(S), ví dụ: https://github.com/org/repo.git",
    },
    "git.auth_required": {
        "en": "The repo requires authentication or access is denied.",
        "ja": "このリポジトリには認証が必要か、アクセスが拒否されました。",
        "vi": "Repo này yêu cầu xác thực hoặc quyền truy cập bị từ chối.",
    },
    "git.repo_not_found": {
        "en": "Repository not found — check the URL.",
        "ja": "リポジトリが見つかりません。URL を確認してください。",
        "vi": "Không tìm thấy repository — kiểm tra lại URL.",
    },
    "git.server_error": {
        "en": "Git server returned an error (HTTP {code}).",
        "ja": "Git サーバーがエラーを返しました（HTTP {code}）。",
        "vi": "Git server trả về lỗi (HTTP {code}).",
    },
    "git.connect_failed": {
        "en": "Could not connect to {url}: {reason}",
        "ja": "{url} に接続できませんでした: {reason}",
        "vi": "Không thể kết nối tới {url}: {reason}",
    },
    "git.timeout": {
        "en": "Connection to the Git server timed out.",
        "ja": "Git サーバーへの接続がタイムアウトしました。",
        "vi": "Kết nối tới Git server đã hết thời gian chờ.",
    },
    "git.invalid_repo": {
        "en": "URL is not a valid Git repository (could not read the branch list).",
        "ja": "有効な Git リポジトリの URL ではありません（ブランチ一覧を読み取れませんでした）。",
        "vi": "URL không phải là một Git repository hợp lệ (không đọc được danh sách nhánh).",
    },
    "git.branch_not_found": {
        "en": 'Branch "{branch}" not found. Available branches: {available}',
        "ja": "「{branch}」というブランチが見つかりません。利用可能なブランチ: {available}",
        "vi": 'Không tìm thấy nhánh "{branch}". Các nhánh khả dụng: {available}',
    },

    # --- git_workspace.py ---
    "gitworkspace.url_required": {
        "en": "Repository URL is required.",
        "ja": "リポジトリ URL を入力してください。",
        "vi": "Vui lòng nhập Repository URL.",
    },
    "gitworkspace.http_only": {
        "en": "Only HTTP(S) Git URLs are supported, e.g. https://github.com/org/repo.git",
        "ja": "HTTP(S) の Git URL のみサポートしています（例: https://github.com/org/repo.git）。",
        "vi": "Chỉ hỗ trợ URL Git dạng HTTP(S), ví dụ: https://github.com/org/repo.git",
    },
    "gitworkspace.git_not_installed": {
        "en": "The 'git' command is not installed (or not on PATH) on the server — the deep-dive agent requires it to clone the repository locally.",
        "ja": "サーバーに 'git' コマンドがインストールされていない（または PATH に含まれていない）ため、ディープダイブ エージェントがリポジトリをローカルに複製できません。",
        "vi": "Lệnh 'git' chưa được cài đặt (hoặc không có trong PATH) trên máy chủ — agent phân tích sâu cần lệnh này để clone repository về máy cục bộ.",
    },
    "gitworkspace.timeout": {
        "en": "Cloning the repository timed out.",
        "ja": "リポジトリの複製がタイムアウトしました。",
        "vi": "Việc clone repository đã hết thời gian chờ.",
    },
    "gitworkspace.branch_not_found": {
        "en": 'Branch "{branch}" not found while cloning.',
        "ja": "複製中に「{branch}」というブランチが見つかりませんでした。",
        "vi": 'Không tìm thấy nhánh "{branch}" khi clone.',
    },
    "gitworkspace.auth_required": {
        "en": "Cloning failed — the repo requires authentication or access was denied.",
        "ja": "複製に失敗しました。このリポジトリには認証が必要か、アクセスが拒否されました。",
        "vi": "Clone thất bại — repo này yêu cầu xác thực hoặc quyền truy cập bị từ chối.",
    },
    "gitworkspace.clone_failed": {
        "en": "Could not clone the repository.",
        "ja": "リポジトリを複製できませんでした。",
        "vi": "Không thể clone repository.",
    },

    # --- git_scan.py ---
    "gitscan.provider_unsupported": {
        "en": "Only GitHub or GitLab repos are supported, and the provider could not be detected from this URL. "
        "For a self-hosted server, pick GitHub or GitLab explicitly in the Git Provider field.",
        "ja": "GitHub または GitLab のリポジトリのみサポートしていますが、この URL からプロバイダーを検出できませんでした。"
        "自社ホストのサーバーの場合は、Git プロバイダー欄で GitHub か GitLab を明示的に選択してください。",
        "vi": "Chỉ hỗ trợ repo GitHub hoặc GitLab, và không thể tự nhận diện nhà cung cấp từ URL này. "
        "Với server tự lưu trữ, hãy chọn rõ GitHub hoặc GitLab trong trường Git Provider.",
    },
    "gitscan.invalid_token": {
        "en": "Invalid Personal Access Token.",
        "ja": "個人アクセストークンが無効です。",
        "vi": "Personal Access Token không hợp lệ.",
    },
    "gitscan.access_denied": {
        "en": "Access denied or the Git host's rate limit was exceeded — add a Personal Access Token.",
        "ja": "アクセスが拒否されたか、Git ホストのレート制限を超えました。個人アクセストークンを追加してください。",
        "vi": "Quyền truy cập bị từ chối hoặc đã vượt giới hạn tần suất của Git host — hãy thêm Personal Access Token.",
    },
    "gitscan.repo_or_branch_not_found": {
        "en": "Repository or branch not found — check the URL/branch.",
        "ja": "リポジトリまたはブランチが見つかりません。URL / ブランチを確認してください。",
        "vi": "Không tìm thấy repository hoặc nhánh — kiểm tra lại URL/nhánh.",
    },
    "gitscan.host_error": {
        "en": "Git host returned an error (HTTP {code}): {body}",
        "ja": "Git ホストがエラーを返しました（HTTP {code}）: {body}",
        "vi": "Git host trả về lỗi (HTTP {code}): {body}",
    },
    "gitscan.connect_failed": {
        "en": "Could not connect to the Git host: {reason}",
        "ja": "Git ホストに接続できませんでした: {reason}",
        "vi": "Không thể kết nối tới Git host: {reason}",
    },
    "gitscan.timeout": {
        "en": "Connection to the Git host timed out.",
        "ja": "Git ホストへの接続がタイムアウトしました。",
        "vi": "Kết nối tới Git host đã hết thời gian chờ.",
    },
    "gitscan.invalid_json": {
        "en": "Invalid response from the Git host (not JSON).",
        "ja": "Git ホストからの応答が不正です（JSON 形式ではありません）。",
        "vi": "Phản hồi từ Git host không hợp lệ (không phải JSON).",
    },
    "gitscan.invalid_github_url": {
        "en": "Invalid GitHub URL — expected the form https://github.com/owner/repo",
        "ja": "無効な GitHub URL です。https://github.com/owner/repo の形式が必要です。",
        "vi": "URL GitHub không hợp lệ — cần đúng dạng https://github.com/owner/repo",
    },
    "gitscan.invalid_gitlab_url": {
        "en": "Invalid GitLab URL.",
        "ja": "無効な GitLab URL です。",
        "vi": "URL GitLab không hợp lệ.",
    },

    # --- excel_parser.py ---
    "excel.openpyxl_missing": {
        "en": "openpyxl is not installed. Run: pip install openpyxl",
        "ja": "openpyxl がインストールされていません。pip install openpyxl を実行してください。",
        "vi": "Chưa cài đặt openpyxl. Chạy: pip install openpyxl",
    },
    "excel.unsupported_format": {
        "en": "Only .xlsx/.xlsm Excel files are supported.",
        "ja": ".xlsx / .xlsm 形式の Excel ファイルのみサポートしています。",
        "vi": "Chỉ hỗ trợ file Excel .xlsx/.xlsm.",
    },
    "excel.read_failed": {
        "en": "Could not read Excel file: {reason}",
        "ja": "Excel ファイルを読み取れませんでした: {reason}",
        "vi": "Không thể đọc file Excel: {reason}",
    },
    "excel.no_worksheets": {
        "en": "Excel file contains no worksheets.",
        "ja": "Excel ファイルにワークシートがありません。",
        "vi": "File Excel không có worksheet nào.",
    },
    "excel.no_tickets_found": {
        "en": "No tickets found. Ensure the sheet has columns like 'Issue Key', 'Summary', 'Status', 'Description'.",
        "ja": "チケットが見つかりません。シートに「Issue Key」「Summary」「Status」「Description」などの列があることを確認してください。",
        "vi": "Không tìm thấy ticket nào. Đảm bảo sheet có các cột như 'Issue Key', 'Summary', 'Status', 'Description'.",
    },
    "excel.no_usable_mapping": {
        "en": "No usable column mapping: map at least Ticket ID or Summary.",
        "ja": "使用できる列マッピングがありません。少なくとも Ticket ID または Summary をマッピングしてください。",
        "vi": "Không có ánh xạ cột nào dùng được: cần ánh xạ ít nhất Ticket ID hoặc Summary.",
    },
    "excel.no_tickets_with_mapping": {
        "en": "No tickets found with the selected column mapping. Check the header row and column choices.",
        "ja": "選択した列マッピングではチケットが見つかりませんでした。ヘッダー行と列の選択を確認してください。",
        "vi": "Không tìm thấy ticket nào với ánh xạ cột đã chọn. Kiểm tra lại dòng tiêu đề và lựa chọn cột.",
    },
}


def translate(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
    """Look up `key` in MESSAGES for `lang`, falling back to English, then
    to the raw key itself if the key is unknown. `kwargs` fill in any
    `{placeholder}` in the template via str.format."""
    lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    entry = MESSAGES.get(key)
    if not entry:
        return key
    template = entry.get(lang) or entry.get(DEFAULT_LANGUAGE) or key
    return template.format(**kwargs) if kwargs else template


def language_from_header(x_language: Optional[str]) -> str:
    return x_language if x_language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


class TranslatableError(Exception):
    """Base for every user-facing backend error. Carries a translation key
    + interpolation kwargs + the HTTP status code to respond with; caught
    by a single global FastAPI exception handler (see main.py) that reads
    the request's X-Language header and returns the translated detail."""

    def __init__(self, key: str, status_code: int = 400, **kwargs):
        self.key = key
        self.status_code = status_code
        self.kwargs = kwargs
        # English fallback so str(exc)/logger.exception(...) stay readable
        # wherever this is logged instead of translated.
        super().__init__(translate(key, DEFAULT_LANGUAGE, **kwargs))
