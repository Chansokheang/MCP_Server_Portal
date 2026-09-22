/* Portal i18n: English source strings, Korean translations applied to the rendered DOM.
 *
 * Pages render English HTML; when the language is Korean, every text node,
 * placeholder, title and aria-label that matches a dictionary entry (or a
 * pattern for strings with numbers and names in them) is replaced after each
 * render. Switching language stores the choice and reloads, so the session
 * and the current page are kept. Strings not in the dictionary stay English. */

const I18N = (() => {
  const dict = {
    // navigation and page titles
    "Overview": "개요", "MCP Registry": "MCP 레지스트리", "MCP Gateways": "MCP 게이트웨이", "MCP Servers": "MCP 서버",
    "Users": "사용자", "Agent Tokens": "에이전트 토큰", "Security": "보안", "Audit Log": "감사 로그", "My access": "내 접근 권한",
    "Gateway details": "게이트웨이 상세", "Backend details": "백엔드 상세", "Access Control": "접근 제어", "Home": "홈", "Me": "나",
    "Gateway": "게이트웨이", "Deployment": "배포", "Theme": "테마", "Sign out": "로그아웃", "Sign in": "로그인", "Language": "언어",
    "Search this page": "이 페이지에서 검색", "Reload this page's data": "페이지 데이터 새로고침", "Help": "도움말", "Notifications": "알림",
    "Toggle theme": "테마 전환", "Not found": "찾을 수 없음", "No such page": "페이지가 없습니다", "Try again": "다시 시도",
    "Could not load this page": "페이지를 불러오지 못했습니다", "MCP Portal · DemoCorp01": "MCP 포털 · DemoCorp01",
    // login
    "Bizplay MCP Portal": "Bizplay MCP 포털", "Register backends, control access, watch every agent call.": "백엔드를 등록하고, 접근을 제어하고, 모든 에이전트 호출을 확인하세요.",
    "Email": "이메일", "Password": "비밀번호",
    // common actions
    "Cancel": "취소", "Save": "저장", "Done": "완료", "Close": "닫기", "Edit": "편집", "Delete": "삭제", "Remove": "제거", "Copy": "복사",
    "Issue": "발급", "Revoke": "폐기", "Rotate": "교체", "Refresh": "새로고침", "Filter": "필터", "All": "전체", "Publish": "게시",
    "Unpublish": "게시 취소", "Deploy": "배포", "Undeploy": "배포 해제", "Connect": "연결", "Disconnect": "연결 해제", "Connect account": "계정 연결",
    "Test connection": "연결 테스트", "Edit connection": "연결 편집", "Register backend": "백엔드 등록", "Register a backend": "백엔드 등록",
    "Register as draft": "초안으로 등록", "Issue token": "토큰 발급", "Issue an agent token": "에이전트 토큰 발급", "Add user": "사용자 추가",
    "Add a user": "사용자 추가", "New gateway": "새 게이트웨이", "Discover": "자동 검색", "Re-discover endpoints": "엔드포인트 다시 검색",
    "Discover and register client": "검색 후 클라이언트 등록", "Refresh tools": "도구 새로고침", "Test sign-in": "로그인 테스트",
    "Edit sign-in settings": "로그인 설정 편집", "Sign in and connect": "로그인하고 연결", "Open sign-in": "로그인 열기",
    "Setup instructions": "연결 안내", "How to connect": "연결 방법", "Create command": "명령 만들기", "Connect command": "연결 명령",
    "Save gateway settings": "게이트웨이 설정 저장", "Save entitlement": "권한 저장", "Edit backends": "백엔드 편집", "Delete gateway": "게이트웨이 삭제",
    "Deploy MCP server": "MCP 서버 배포", "Deploy as MCP server": "MCP 서버로 배포", "Undeploy MCP server": "MCP 서버 배포 해제",
    "Deploy an MCP server": "MCP 서버 배포", "Load Bizplay sample spec": "Bizplay 샘플 스펙 불러오기", "Switch to Open mode": "오픈 모드로 전환",
    "Register a new API instead": "대신 새 API 등록", "Change on backend": "백엔드에서 변경", "Someone not listed…": "목록에 없는 사람…",
    "Table view": "표 보기", "All backends": "전체 백엔드", "All gateways": "전체 게이트웨이", "Copy the endpoint": "엔드포인트 복사",
    // table headers and labels
    "Token": "토큰", "Bizplay user": "Bizplay 사용자", "Company": "회사", "Status": "상태", "Expires": "만료", "Last used": "마지막 사용",
    "User": "사용자", "Role": "역할", "Groups": "그룹", "Portal sign-in": "포털 로그인", "Tokens": "토큰", "Linked accounts": "연결된 계정",
    "Name": "이름", "Kind": "종류", "Type and auth": "종류 및 인증", "Backend": "백엔드", "Tools": "도구", "Address": "주소", "Endpoint": "엔드포인트",
    "Backends": "백엔드", "Tool": "도구", "Description": "설명", "Allowed roles": "허용 역할", "Enabled": "활성", "Path": "경로",
    "Time (UTC)": "시간 (UTC)", "Arguments": "인수", "Outcome": "결과", "Detail": "상세", "Check": "점검", "Result": "결과",
    "Credential": "자격 증명", "Secret": "시크릿", "Rotated": "교체됨", "Signs in as": "로그인 계정", "Token expires": "토큰 만료", "Scope": "범위",
    "Label": "라벨", "Auth": "인증", "Transport": "전송 방식", "Header": "헤더", "Tool names": "도구 이름", "Served on": "제공 엔드포인트",
    "Sent as": "전송 형식", "Login URL": "로그인 URL", "Token field": "토큰 필드", "Credentials": "자격 증명", "Auth server": "인증 서버",
    "Client id": "클라이언트 ID", "Linked users": "연결된 사용자", "Upstream API": "업스트림 API", "Tool names on gateways": "게이트웨이의 도구 이름",
    "Connected": "연결됨", "Linked": "연결됨", "Entitlement": "권한", "Type": "종류", "Companies": "회사", "Built from": "생성 원본",
    // chips and states
    "Bearer": "베어러", "Network": "네트워크", "Open": "오픈", "OAuth per user": "사용자별 OAuth", "Login endpoint": "로그인 엔드포인트",
    "MCP server": "MCP 서버", "Member": "멤버", "Managed by admin": "관리자가 관리", "Required": "필수", "Not required": "불필요",
    "Active": "활성", "Expired": "만료됨", "Revoked": "폐기됨", "Draft": "초안", "Published": "게시됨", "Deployed": "배포됨", "Undeployed": "배포 해제됨",
    "denied": "거부", "error": "오류", "pass": "통과", "fail": "실패", "Everyone": "모두", "employee": "직원", "manager": "매니저",
    "no groups": "그룹 없음", "none": "없음", "never": "없음", "Denied": "거부됨", "Errors": "오류", "Succeeded": "성공", "All calls": "전체 호출",
    "Live": "실시간", "Registry live": "레지스트리 실시간", "Agent token required": "에이전트 토큰 필수", "Auth server configured": "인증 서버 설정됨",
    "Auth server not configured": "인증 서버 미설정", "Login endpoint configured": "로그인 엔드포인트 설정됨", "Login endpoint not configured": "로그인 엔드포인트 미설정",
    "Open to every entitled caller": "권한 있는 모든 호출자에게 개방", "No token: every caller is the demo user": "토큰 없음: 모든 호출자가 데모 사용자",
    "Never rotated": "교체된 적 없음", "confirm first": "먼저 확인", "not published": "미게시", "inherit from backend": "백엔드 설정 상속",
    // tabs and sections
    "Checklist": "체크리스트", "Defaults": "기본값", "Upstream credentials": "업스트림 자격 증명", "Available to deploy": "배포 가능",
    "My agent tokens": "내 에이전트 토큰", "Connected accounts": "연결된 계정", "Gateways you can use": "사용할 수 있는 게이트웨이",
    "Gateway settings": "게이트웨이 설정", "Tools on this endpoint": "이 엔드포인트의 도구", "Who can use this backend": "이 백엔드를 사용할 수 있는 사람",
    "Who can use this gateway": "이 게이트웨이를 사용할 수 있는 사람", "Tool policy": "도구 정책", "Sign-in": "로그인",
    "Gateway calls per day": "일별 게이트웨이 호출", "Gateway calls by backend": "백엔드별 게이트웨이 호출", "Tools enabled per backend": "백엔드별 활성 도구",
    "Backends on the shared gateway": "공유 게이트웨이의 백엔드", "Use it from any MCP client": "어떤 MCP 클라이언트에서든 사용",
    "Claude Code, one line": "Claude Code, 한 줄", "Claude Desktop, add under mcpServers": "Claude Desktop, mcpServers 아래에 추가",
    "Check it from a terminal": "터미널에서 확인", "Backends that need your own sign-in": "개인 로그인이 필요한 백엔드", "Calls by backend": "백엔드별 호출",
    "Open items": "미완료 항목", "Everything": "전체", "Curated Bizplay gateway": "큐레이션된 Bizplay 게이트웨이",
    // stats
    "Backends served": "제공 중인 백엔드", "Tools enabled for agents": "에이전트에 활성화된 도구", "Checks passing": "통과한 점검", "Security score": "보안 점수",
    "MCP servers deployed": "배포된 MCP 서버", "Credentials rotated at least once": "한 번 이상 교체된 자격 증명",
    "Registered backends not deployed yet": "아직 배포되지 않은 등록 백엔드", "Tools served by them": "제공되는 도구",
    // form labels
    "Provider name": "제공자 이름", "Base URL of the existing API": "기존 API의 기본 URL", "URL of the MCP server": "MCP 서버 URL",
    "How is the API protected?": "API는 어떻게 보호되나요?", "How is the MCP server protected?": "MCP 서버는 어떻게 보호되나요?",
    "Service bearer token the gateway will send": "게이트웨이가 보낼 서비스 베어러 토큰", "Service bearer token": "서비스 베어러 토큰",
    "Gateway address the API allows": "API가 허용하는 게이트웨이 주소", "OpenAPI spec (JSON)": "OpenAPI 스펙 (JSON)", "Authorization URL": "인가 URL",
    "Token URL": "토큰 URL", "Client secret": "클라이언트 시크릿", "Scopes": "스코프", "Resource (RFC 8707)": "리소스 (RFC 8707)",
    "Request body": "요청 본문", "Token field in the response": "응답의 토큰 필드", "Expiry field (optional)": "만료 필드 (선택)",
    "Lifetime if no expiry field (minutes)": "만료 필드가 없을 때 유효 시간 (분)", "Send the token in header": "토큰을 보낼 헤더", "Scheme prefix": "스킴 접두어",
    "Whose credentials": "누구의 자격 증명", "Service account username": "서비스 계정 사용자 이름", "Service account password": "서비스 계정 비밀번호",
    "Bizplay user id": "Bizplay 사용자 ID", "Access groups": "접근 그룹", "Company (corpNo)": "회사 (사업자번호)", "Portal password": "포털 비밀번호",
    "AI agent": "AI 에이전트", "Expires in (days)": "만료 (일)", "Backend type": "백엔드 종류", "Backend to deploy": "배포할 백엔드",
    "Public MCP endpoint": "공개 MCP 엔드포인트", "Token lifetime in days": "토큰 유효 기간 (일)", "Require an agent token": "에이전트 토큰 필수",
    "Only these groups": "지정 그룹만", "Only these companies": "지정 회사만", "Only these access groups": "지정 접근 그룹만",
    "Everyone with access": "접근 권한이 있는 모두", "Everyone with a token": "토큰이 있는 모두", "Confirm before call": "호출 전 확인",
    "Description the model sees": "모델이 보는 설명", "Tool name the agent calls": "에이전트가 호출하는 도구 이름", "Existing MCP server": "기존 MCP 서버",
    "Paste its OpenAPI spec. The gateway generates the tools.": "OpenAPI 스펙을 붙여넣으세요. 게이트웨이가 도구를 생성합니다.",
    "Give its URL. The gateway proxies its tools.": "URL을 입력하세요. 게이트웨이가 도구를 프록시합니다.",
    "Bearer token: it rejects anonymous calls (recommended)": "베어러 토큰: 익명 호출을 거부함 (권장)",
    "Bearer token: the API rejects anonymous calls": "베어러 토큰: API가 익명 호출을 거부함",
    "Network-isolated: no token, only the gateway's address can reach it": "네트워크 격리: 토큰 없음, 게이트웨이 주소만 접근 가능",
    "Open: anyone can call it (demo data only, recorded as accepted risk)": "오픈: 누구나 호출 가능 (데모 데이터 전용, 수용된 위험으로 기록)",
    "OAuth: each user links their own account; the gateway sends that user's token": "OAuth: 사용자가 각자 계정을 연결하고, 게이트웨이가 그 사용자의 토큰을 보냄",
    "Login endpoint: it has its own username-and-password sign-in; the gateway signs in and sends the token": "로그인 엔드포인트: 자체 아이디·비밀번호 로그인이 있고, 게이트웨이가 로그인해 토큰을 보냄",
    "Login endpoint: the gateway signs in with a username and password": "로그인 엔드포인트: 게이트웨이가 아이디와 비밀번호로 로그인",
    "Service account: one username and password shared by every caller": "서비스 계정: 모든 호출자가 공유하는 하나의 아이디와 비밀번호",
    "Each user: people sign in with their own username and password": "사용자별: 각자 자신의 아이디와 비밀번호로 로그인",
    "Dot path into the JSON answer.": "JSON 응답 안의 점(.) 경로.", "Added to the Users page as well.": "사용자 페이지에도 추가됩니다.",
    "The token works from any MCP client; say which one in the label.": "토큰은 어떤 MCP 클라이언트에서든 쓸 수 있습니다. 라벨에 어느 것인지 적어 두세요.",
    "What agent tokens carry as the caller and what the audit log shows.": "에이전트 토큰이 호출자로 담는 값이며 감사 로그에 표시됩니다.",
    "The corp number the gateway limits this person's calls and results to.": "게이트웨이가 이 사람의 호출과 결과를 제한하는 사업자번호입니다.",
    "With a password the person signs in as a member and manages their own tokens and linked accounts.": "비밀번호가 있으면 멤버로 로그인해 자신의 토큰과 연결 계정을 직접 관리합니다.",
    "leave blank to keep the stored one": "비워 두면 저장된 값 유지", "stored, never shown again": "저장됨, 다시 표시되지 않음", "stored, leave blank to keep": "저장됨, 비워 두면 유지",
    "issued by the provider (stored, never shown again)": "제공자가 발급 (저장됨, 다시 표시되지 않음)", "issued by the auth server": "인증 서버가 발급",
    "if the auth server issued one": "인증 서버가 발급한 경우", "finance, hr (comma separated)": "finance, hr (쉼표로 구분)", "leave empty: no portal sign-in": "비워 두면 포털 로그인 없음",
    "(unchanged)": "(변경 없음)", "space separated, e.g. tasks:read": "공백으로 구분, 예: tasks:read", "MCP servers: their own URL": "MCP 서버: 자체 URL",
    "Bearer (empty for none)": "Bearer (없으면 비움)", "expiresIn (seconds)": "expiresIn (초)", "User or tool": "사용자 또는 도구", "Filter audit log": "감사 로그 필터",
    // descriptions and callouts
    "Copy it now. It will not be shown again.": "지금 복사하세요. 다시 표시되지 않습니다.",
    "The portal connects to the server now and reads its tool list. Tools marked read-only by the server start enabled; the rest start off and can be switched on under Access Control.": "포털이 지금 서버에 연결해 도구 목록을 읽습니다. 서버가 읽기 전용으로 표시한 도구는 활성 상태로, 나머지는 비활성 상태로 시작하며 접근 제어에서 켤 수 있습니다.",
    "Open backend.": "오픈 백엔드.",
    "The gateway still authenticates agents, applies tool policy, and limits results to the caller's company, but anyone who knows the URL can bypass it. The overview will show this as an accepted risk.": "게이트웨이는 여전히 에이전트를 인증하고 도구 정책을 적용하며 결과를 호출자의 회사로 제한하지만, URL을 아는 누구나 우회할 수 있습니다. 개요에 수용된 위험으로 표시됩니다.",
    "Agent tokens and linked accounts are issued to people listed here. A token takes its role, company and groups from the person, so they are set once. Users with a portal password sign in as members and issue their own tokens and link their own accounts; the rest are managed here.": "에이전트 토큰과 연결 계정은 여기에 등록된 사람에게 발급됩니다. 토큰은 역할·회사·그룹을 그 사람에게서 가져오므로 한 번만 설정하면 됩니다. 포털 비밀번호가 있는 사용자는 멤버로 로그인해 자신의 토큰과 계정을 직접 관리하고, 나머지는 여기서 관리합니다.",
    "Role, company and groups come from the": "역할, 회사, 그룹은", "page, so they cannot disagree with the token.": "페이지에서 가져오므로 토큰과 어긋나지 않습니다.",
    "The gateway calls the login URL itself, caches the token, and signs in again when it expires or the API answers 401. With per-user credentials each person connects on their": "게이트웨이가 직접 로그인 URL을 호출하고 토큰을 캐시하며, 만료되거나 API가 401을 응답하면 다시 로그인합니다. 사용자별 자격 증명이면 각자",
    "page and the API sees them, not a shared account.": "페이지에서 연결하고, API는 공유 계정이 아닌 그 사람을 봅니다.",
    "Results are limited to the company on the caller's token, and every call is written to the audit log. Connect instructions live on each endpoint's page under Served on.": "결과는 호출자 토큰의 회사로 제한되고, 모든 호출은 감사 로그에 기록됩니다. 연결 안내는 각 엔드포인트 페이지의 제공 엔드포인트 아래에 있습니다.",
    "Secrets are masked here and never shown again after rotation. The mockup keeps them in a JSON file; production keeps them in a vault.": "시크릿은 여기서 가려지며 교체 후 다시 표시되지 않습니다. 목업은 JSON 파일에, 운영 환경은 볼트에 보관합니다.",
    "Token lifetime, the public address and upstream credentials stay on the Security page; they are not per gateway.": "토큰 유효 기간, 공개 주소, 업스트림 자격 증명은 보안 페이지에 있으며 게이트웨이별 설정이 아닙니다.",
    "Changes save as you make them. Token requirement and who may use an endpoint are set per gateway on its own page; these are the portal-wide defaults.": "변경 사항은 즉시 저장됩니다. 토큰 필수 여부와 엔드포인트 사용자는 각 게이트웨이 페이지에서 정하며, 여기는 포털 전체 기본값입니다.",
    "Register a REST API with its OpenAPI spec, or an MCP server that already exists. Neither is changed.": "OpenAPI 스펙으로 REST API를 등록하거나 이미 있는 MCP 서버를 등록하세요. 어느 쪽도 변경되지 않습니다.",
    "Register this redirect URL with the auth server:": "이 리디렉션 URL을 인증 서버에 등록하세요:",
    ". MCP servers that publish their auth metadata can fill all of this in with": ". 인증 메타데이터를 공개하는 MCP 서버는", "on the provider page, and register the gateway as a client by themselves.": "(제공자 페이지)로 이 항목을 모두 채우고 게이트웨이를 클라이언트로 직접 등록할 수 있습니다.",
    "A sign-in tab was opened. When it finishes, it returns to this portal and the account appears under Connected accounts.": "로그인 탭이 열렸습니다. 완료되면 이 포털로 돌아오고 계정이 연결된 계정 아래에 표시됩니다.",
    "The browser blocked the pop-up. Open this address instead:": "브라우저가 팝업을 차단했습니다. 대신 이 주소를 여세요:",
    "Who should the agent act as? A token is issued for this command.": "에이전트가 누구로 동작할까요? 이 명령을 위한 토큰이 발급됩니다.",
    "This backend wants each user's own token from its auth server. The AI client never sees that server: a user links their account here once, the gateway keeps the refresh token and attaches the right access token to that user's calls. A caller without a linked account gets a message telling them to connect it.": "이 백엔드는 인증 서버에서 발급된 사용자별 토큰을 요구합니다. AI 클라이언트는 그 서버를 보지 못합니다. 사용자가 여기서 한 번 계정을 연결하면 게이트웨이가 리프레시 토큰을 보관하고 그 사용자의 호출에 맞는 액세스 토큰을 붙입니다. 연결하지 않은 호출자에게는 연결하라는 메시지가 돌아갑니다.",
    "Each person signs in with their own username and password for this backend, so it sees the real user. The gateway keeps the credentials, signs in when the token expires or the API answers 401, and never uses one person's sign-in for another.": "각자 이 백엔드의 아이디와 비밀번호로 로그인하므로 백엔드는 실제 사용자를 봅니다. 게이트웨이가 자격 증명을 보관하고, 토큰이 만료되거나 API가 401을 응답하면 다시 로그인하며, 한 사람의 로그인을 다른 사람에게 쓰지 않습니다.",
    "No backend needs a personal sign-in.": "개인 로그인이 필요한 백엔드가 없습니다.",
    // empty states
    "No tokens here": "토큰이 없습니다", "No tokens yet": "아직 토큰이 없습니다", "No users": "사용자가 없습니다", "No calls yet": "아직 호출이 없습니다",
    "Nothing here": "기록이 없습니다", "No gateway yet": "아직 게이트웨이가 없습니다", "No upstream credentials": "업스트림 자격 증명 없음",
    "Not served anywhere yet": "아직 어디에도 제공되지 않음", "No accounts linked yet.": "아직 연결된 계정이 없습니다.", "No accounts connected yet.": "아직 연결된 계정이 없습니다.",
    "Issue one to connect an AI agent to the gateway over HTTP.": "HTTP로 AI 에이전트를 게이트웨이에 연결하려면 토큰을 발급하세요.",
    "Issue one and paste it into your AI client. It identifies you on every call.": "토큰을 발급해 AI 클라이언트에 붙여넣으세요. 모든 호출에서 당신을 식별합니다.",
    "Add the people who will call the gateway through an AI agent.": "AI 에이전트를 통해 게이트웨이를 호출할 사람을 추가하세요.",
    "Every gateway call is recorded with who made it and the outcome.": "모든 게이트웨이 호출은 호출자와 결과와 함께 기록됩니다.",
    "An admin creates gateways and decides who may use them.": "관리자가 게이트웨이를 만들고 사용자를 정합니다.",
    "Backends in bearer mode get one when they are registered.": "베어러 모드 백엔드는 등록 시 자격 증명을 받습니다.",
    "Publish it to put it on the shared gateway, deploy it as its own MCP server, or add it to a named gateway.": "게시하면 공유 게이트웨이에 올라가고, 자체 MCP 서버로 배포하거나 이름 있는 게이트웨이에 추가할 수 있습니다.",
    "Traffic per backend appears here.": "백엔드별 트래픽이 여기에 표시됩니다.", "Register a backend first.": "먼저 백엔드를 등록하세요.",
    "Register one in the MCP Registry.": "MCP 레지스트리에서 등록하세요.", "Enable some on the backends' pages and they appear here.": "백엔드 페이지에서 도구를 켜면 여기에 표시됩니다.",
    "Every registered backend is already deployed": "등록된 백엔드가 모두 배포되었습니다", "Register another backend in the MCP Registry to deploy it here.": "MCP 레지스트리에서 다른 백엔드를 등록하면 여기서 배포할 수 있습니다.",
    "Deploy one from a registered backend, or register a new API and deploy it in one go.": "등록된 백엔드에서 배포하거나, 새 API를 등록하면서 한 번에 배포하세요.",
    // toasts and confirms
    "Copied": "복사됨", "Token is on your clipboard": "토큰이 클립보드에 복사되었습니다", "Paste it into your terminal": "터미널에 붙여넣으세요",
    "Token issued": "토큰 발급됨", "Token revoked": "토큰 폐기됨", "Revoke failed": "폐기 실패", "Account linked": "계정 연결됨", "Account connected": "계정 연결됨",
    "Account disconnected": "계정 연결 해제됨", "Disconnect failed": "연결 해제 실패", "Sign-in failed": "로그인 실패", "User saved": "사용자 저장됨",
    "User added": "사용자 추가됨", "User removed": "사용자 제거됨", "Registered as draft": "초안으로 등록됨", "Connection updated": "연결 업데이트됨",
    "Settings saved": "설정 저장됨", "Gateway settings saved": "게이트웨이 설정 저장됨", "Entitlement saved": "권한 저장됨", "Policy saved": "정책 저장됨",
    "Save failed": "저장 실패", "Action failed": "작업 실패", "Delete failed": "삭제 실패", "Provider deleted": "제공자 삭제됨", "Gateway deleted": "게이트웨이 삭제됨",
    "Tools refreshed": "도구 새로고침됨", "MCP server deployed": "MCP 서버 배포됨", "Registered, but not deployed": "등록됐지만 배포되지 않음",
    "OAuth endpoints discovered": "OAuth 엔드포인트 검색됨", "Client registered": "클라이언트 등록됨", "Endpoints discovered": "엔드포인트 검색됨",
    "Rotation failed": "교체 실패", "No users yet": "아직 사용자가 없습니다", "Add the person on the Users page first": "먼저 사용자 페이지에서 추가하세요",
    "The agent can no longer call the gateway": "에이전트가 더 이상 게이트웨이를 호출할 수 없습니다", "Recorded as an accepted risk": "수용된 위험으로 기록됨",
    "Revoke this token? The agent loses access immediately.": "이 토큰을 폐기할까요? 에이전트의 접근이 즉시 끊깁니다.",
    "Disconnect this account? Your calls to it are refused until you link it again.": "이 계정의 연결을 해제할까요? 다시 연결할 때까지 호출이 거부됩니다.",
    "Rotate this credential? The provider must accept the new token before the old one is retired.": "이 자격 증명을 교체할까요? 이전 토큰을 폐기하기 전에 제공자가 새 토큰을 받아들여야 합니다.",
    "Session expired, please sign in again": "세션이 만료되었습니다. 다시 로그인하세요", "Invalid email or password": "이메일 또는 비밀번호가 올바르지 않습니다",
  };

  // Strings with a number or a name in them. Each rule is [pattern, replacement].
  const rules = [
    [/^(\d+) tools?$/, "도구 $1개"], [/^(\d+) of (\d+) enabled$/, "$2개 중 $1개 활성"], [/^(\d+) active$/, "활성 $1개"],
    [/^(\d+) endpoint\(s\)$/, "엔드포인트 $1개"], [/^(\d+) tool\(s\)$/, "도구 $1개"], [/^(\d+) backend\(s\)$/, "백엔드 $1개"],
    [/^(\d+) user\(s\) linked\.?$/, "사용자 $1명 연결됨"], [/^(\d+) connected$/, "$1명 연결됨"], [/^Each user \((\d+) connected\)$/, "사용자별 ($1명 연결됨)"],
    [/^Newest first, (\d+) call\(s\)$/, "최신순, $1건"], [/^Issued by (.+)$/, "$1 발급"], [/^Connect an account on (.+)$/, "$1 계정 연결"],
    [/^Connect to (.+)$/, "$1에 연결"], [/^Connection test: (.+)$/, "연결 테스트: $1"], [/^Waiting for (.+) to sign in$/, "$1의 로그인을 기다리는 중"],
    [/^Edit (.+)$/, "$1 편집"], [/^Delete (.+)\?$/, "$1을(를) 삭제할까요?"], [/^Remove (.+)\? Their tokens are revoked and their linked accounts dropped\.$/, "$1을(를) 제거할까요? 토큰이 폐기되고 연결된 계정이 삭제됩니다."],
    [/^Disconnect (.+)\? Their calls to (.+) are refused until they link the account again\.$/, "$1의 연결을 해제할까요? 다시 연결할 때까지 $2 호출이 거부됩니다."],
    [/^Signed in as (.+), (.+)$/, "$1(으)로 로그인, $2"], [/^Linked (.+)$/, "연결됨 $1"], [/^Signed in to (.+) as (.+)$/, "$1에 $2(으)로 로그인했습니다"],
    [/^(.+) can now use this backend(.*)$/, "$1이(가) 이제 이 백엔드를 사용할 수 있습니다$2"], [/^(.+) username$/, "$1 사용자 이름"], [/^(.+) password$/, "$1 비밀번호"],
    [/^(.+) \(auto-refresh\)$/, "$1 (자동 갱신)"], [/^(.+) \(auto sign-in\)$/, "$1 (자동 로그인)"], [/^Token valid until (.+)\.$/, "토큰 유효 기한 $1."],
    [/^Registered (.+) by (.+)$/, "$2이(가) $1에 등록"], [/^groups: (.+)$/, "그룹: $1"],
  ];


  // Second batch: overview, registry, gateways, security, access control, connect guides.
  Object.assign(dict, {
    // overview
    "Claude, ChatGPT, Copilot, Agentforce": "Claude, ChatGPT, Copilot, Agentforce", "agent token": "에이전트 토큰", "MCP Gateway": "MCP 게이트웨이",
    "authentication, tool policy, company scope, audit": "인증, 도구 정책, 회사 범위, 감사", "service or user token": "서비스 또는 사용자 토큰",
    "REST API or MCP server": "REST API 또는 MCP 서버", "unchanged; may also be deployed as its own MCP server": "변경 없음, 자체 MCP 서버로도 배포 가능",
    "Audit log": "감사 로그", "last 14 days": "최근 14일", "Registry": "레지스트리", "calls": "호출", "enabled": "활성", "registered but off": "등록됐지만 꺼짐",
    "total": "합계", "Other": "기타", "Live": "실시간",
    // registry, gateways, servers
    "shared gateway": "공유 게이트웨이", "Setup": "설정", "every backend the caller is entitled to": "호출자에게 권한이 있는 모든 백엔드",
    "shared endpoint, every backend the caller is entitled to": "공유 엔드포인트, 호출자에게 권한이 있는 모든 백엔드", "Named gateway": "이름 있는 게이트웨이",
    "puts a backend on the shared gateway endpoint, with this portal's tool policy enforced.": "은(는) 백엔드를 공유 게이트웨이 엔드포인트에 올리고 이 포털의 도구 정책을 적용합니다.",
    "additionally gives it an MCP server of its own at": "은(는) 추가로 다음 주소에 자체 MCP 서버를 만듭니다:",
    ", with plain tool names, for teams that want one product per connector. Both take effect on the next request, no restart.": ". 접두어 없는 도구 이름으로, 커넥터 하나에 제품 하나를 원하는 팀을 위한 것입니다. 둘 다 다음 요청부터 적용되며 재시작이 없습니다.",
    "A named gateway is one address that serves a chosen set of backends, prefixed like the shared endpoint: one connector for a team or a product line, without giving out everything. Entitlements, tool policy, tokens and audit apply unchanged. For a single backend with plain tool names, deploy it as an MCP server instead.": "이름 있는 게이트웨이는 선택한 백엔드 묶음을 공유 엔드포인트처럼 접두어를 붙여 제공하는 하나의 주소입니다. 전부를 내주지 않고 팀이나 제품군에 커넥터 하나를 줄 수 있습니다. 권한, 도구 정책, 토큰, 감사는 그대로 적용됩니다. 접두어 없는 도구 이름의 단일 백엔드는 MCP 서버로 배포하세요.",
    "An MCP server here is one backend served on its own address (": "여기서 MCP 서버란 자체 주소(",
    ") with plain tool names: the shape a vendor's own MCP app has in claude.ai or ChatGPT. It runs inside this gateway, so deploying needs no restart, and the same agent tokens, tool policy, company scoping and audit apply. The same backend keeps working on the shared gateway with prefixed names.": ")에서 접두어 없는 도구 이름으로 제공되는 백엔드 하나입니다. claude.ai나 ChatGPT에서 벤더의 자체 MCP 앱이 갖는 형태입니다. 이 게이트웨이 안에서 실행되므로 배포에 재시작이 없고, 같은 에이전트 토큰, 도구 정책, 회사 범위, 감사가 적용됩니다. 같은 백엔드는 공유 게이트웨이에서 접두어 붙은 이름으로 계속 동작합니다.",
    "Serving": "제공 중", "Deployed as MCP server": "MCP 서버로 배포됨", "Gateways": "게이트웨이", "no token required": "토큰 불필요",
    "none required on this endpoint": "이 엔드포인트에서는 불필요", "prefixed by backend id": "백엔드 ID 접두어", "no prefix": "접두어 없음", "streamable HTTP": "streamable HTTP",
    "Default (not required)": "기본값 (불필요)", "Default (required)": "기본값 (필수)",
    "Callers must present a portal-issued token on this endpoint. Applies on the next request; no restart. Without a token every caller is the demo identity and no per-user rule can apply.": "호출자는 이 엔드포인트에서 포털이 발급한 토큰을 제시해야 합니다. 다음 요청부터 적용되며 재시작이 없습니다. 토큰이 없으면 모든 호출자가 데모 신원이 되어 사용자별 규칙을 적용할 수 없습니다.",
    "Checked before anything else. Each backend's own entitlement and tool policy still apply on top.": "가장 먼저 확인됩니다. 각 백엔드의 권한과 도구 정책은 그 위에 추가로 적용됩니다.",
    "Comma separated company ids from the caller's token.": "호출자 토큰의 회사 ID를 쉼표로 구분해 입력.",
    "Comma separated company ids, matched against the company on the caller's token.": "쉼표로 구분한 회사 ID. 호출자 토큰의 회사와 대조됩니다.",
    "Decides which callers see this backend at all, on every gateway that serves it. Everyone else gets no tools from it and is refused if they try. Tool policy below applies on top.": "이 백엔드를 제공하는 모든 게이트웨이에서 어떤 호출자가 이 백엔드를 볼 수 있는지 정합니다. 그 외에는 도구가 보이지 않고 호출하면 거부됩니다. 아래 도구 정책은 그 위에 적용됩니다.",
    "Applies on the next call, on the shared gateway, named gateways and this backend's own MCP server alike.": "다음 호출부터 공유 게이트웨이, 이름 있는 게이트웨이, 이 백엔드의 자체 MCP 서버 모두에 적용됩니다.",
    "The description field is what the model reads when it chooses a tool; the placeholder shows what the spec or server provides today. A tool with groups listed is shown only to callers in one of them; blank means every entitled caller. Changes apply on the next call.": "설명 필드는 모델이 도구를 고를 때 읽는 내용이며, 자리 표시자는 스펙이나 서버가 현재 제공하는 설명입니다. 그룹이 지정된 도구는 그 그룹의 호출자에게만 보이고, 비워 두면 권한 있는 모두에게 보입니다. 변경은 다음 호출부터 적용됩니다.",
    "read": "읽기", "write": "쓰기", "Tools proxied from the MCP server, unchanged": "MCP 서버에서 그대로 프록시된 도구",
    "The upstream accepts anonymous calls, so the gateway carries all the enforcement.": "업스트림이 익명 호출을 허용하므로 게이트웨이가 모든 통제를 맡습니다.",
    "The gateway sends a stored service token on every call.": "게이트웨이가 저장된 서비스 토큰을 모든 호출에 보냅니다.",
    "The gateway signs in with a service account and sends the token it gets.": "게이트웨이가 서비스 계정으로 로그인해 받은 토큰을 보냅니다.",
    // security
    "Pass": "통과", "Fail": "실패", "Bizplay API endpoints require a bearer token": "Bizplay API 엔드포인트가 베어러 토큰을 요구함",
    "Every /api/* call from the gateway carries the service token; the API answers 401 without it.": "게이트웨이의 모든 /api/* 호출이 서비스 토큰을 담으며, 없으면 API가 401을 응답합니다.",
    "No published provider is an open (unauthenticated) API": "게시된 제공자 중 오픈(무인증) API가 없음",
    "MCP gateway requires a bearer token": "MCP 게이트웨이가 베어러 토큰을 요구함",
    "The default for every gateway endpoint; an endpoint may override it on its own page.": "모든 게이트웨이 엔드포인트의 기본값이며, 각 엔드포인트 페이지에서 재정의할 수 있습니다.",
    "Write tools require user confirmation": "쓰기 도구는 사용자 확인이 필요함", "No agent token lives longer than 90 days": "90일을 넘는 에이전트 토큰이 없음",
    "All tokens expire within 90 days.": "모든 토큰이 90일 안에 만료됩니다.", "OAuth 2.1 identity provider connected": "OAuth 2.1 ID 제공자 연결됨",
    "Mockup uses portal-issued static tokens. Production: connect Bizplay SSO.": "목업은 포털이 발급한 정적 토큰을 사용합니다. 운영 환경: Bizplay SSO 연결.",
    "Upstream credentials stored in a vault": "업스트림 자격 증명을 볼트에 보관", "Mockup stores credentials in a JSON file. Production: KMS / vault.": "목업은 자격 증명을 JSON 파일에 보관합니다. 운영 환경: KMS / 볼트.",
    "Two of these stay open by design in the mockup: OAuth 2.1 for agents and a vault for secrets are production work. The rest are decided by the Defaults tab, each gateway's own settings, and how each backend is registered.": "이 중 둘은 목업에서 의도적으로 미완료입니다. 에이전트용 OAuth 2.1과 시크릿 볼트는 운영 작업입니다. 나머지는 기본값 탭, 각 게이트웨이 설정, 각 백엔드 등록 방식에 따라 정해집니다.",
    "How a caller is identified": "호출자 식별 방식", "issuer: portal": "발급자: 포털", "Every gateway endpoint reads the same claims from an agent token:": "모든 게이트웨이 엔드포인트가 에이전트 토큰에서 같은 클레임을 읽습니다:",
    "is the Bizplay user,": "은(는) Bizplay 사용자,", "drive tool policy and company scoping,": "은(는) 도구 정책과 회사 범위를,",
    "drive entitlement. Tokens are issued by this portal today; production points the issuer at Bizplay SSO (OAuth 2.1 / OIDC) so they become signed JWTs verified by key.": "은(는) 권한을 결정합니다. 현재는 이 포털이 토큰을 발급하며, 운영 환경에서는 발급자를 Bizplay SSO(OAuth 2.1 / OIDC)로 바꿔 키로 검증되는 서명된 JWT가 됩니다.",
    "Records the policy that every /api/* call carries the service token. Enforced by the provider's own API, not here.": "모든 /api/* 호출이 서비스 토큰을 담는다는 정책을 기록합니다. 여기가 아니라 제공자의 API가 강제합니다.",
    "Gateways require an agent token by default": "게이트웨이가 기본적으로 에이전트 토큰을 요구",
    "The default for every gateway endpoint; each gateway can override it on its own page. Applies on the next request. Off means anyone who reaches an endpoint is the same demo user.": "모든 게이트웨이 엔드포인트의 기본값이며 각 게이트웨이 페이지에서 재정의할 수 있습니다. 다음 요청부터 적용됩니다. 끄면 엔드포인트에 도달한 누구나 같은 데모 사용자가 됩니다.",
    "Write tools ask for confirmation": "쓰기 도구는 확인을 요청", "Turning this on sets confirm-before-call on every write tool of every backend at once.": "켜면 모든 백엔드의 모든 쓰기 도구에 호출 전 확인이 한 번에 설정됩니다.",
    "Default agent token lifetime": "기본 에이전트 토큰 유효 기간", "Days before a newly issued agent token expires. The checklist flags anything over 90.": "새로 발급된 에이전트 토큰이 만료되기까지의 일수. 체크리스트는 90일 초과를 표시합니다.",
    "days": "일", "bearer token the gateway sends": "게이트웨이가 보내는 베어러 토큰", "signs in as (no username)": "로그인 계정 (사용자 이름 없음)",
    // connect guides
    "Works today": "지금 바로 사용 가능", "Needs hosting and OAuth": "호스팅과 OAuth 필요", "Open the config file": "설정 파일 열기", "Windows:": "Windows:", "macOS:": "macOS:",
    "Option A, connect to this gateway": "방법 A, 이 게이트웨이에 연결", "Option B, run a local copy instead": "방법 B, 로컬 복사본 실행",
    "Quit Claude Desktop from the system tray, then reopen": "시스템 트레이에서 Claude Desktop을 종료한 뒤 다시 실행",
    "Closing the window is not enough. The tools appear in the tools menu of a new chat.": "창을 닫는 것만으로는 부족합니다. 도구는 새 채팅의 도구 메뉴에 나타납니다.",
    "Try it": "사용해 보기", "Ask for something this API covers, for example a call to": "이 API가 다루는 것을 요청해 보세요. 예를 들어 다음 도구 호출:",
    "Add the server": "서버 추가", "Check it connected": "연결 확인", "Remove it later": "나중에 제거", "Any MCP client": "모든 MCP 클라이언트",
    "Any client that speaks MCP over HTTP can use this API. It needs the endpoint and an Authorization header.": "HTTP로 MCP를 사용하는 어떤 클라이언트든 이 API를 쓸 수 있습니다. 엔드포인트와 Authorization 헤더가 필요합니다.",
    "Connection details": "연결 정보", "Python, with the FastMCP client": "Python, FastMCP 클라이언트", "Raw HTTP, to check the token": "토큰 확인용 HTTP 요청",
    "Without the header this returns 401. That is the gateway refusing an unauthenticated agent.": "헤더가 없으면 401이 돌아옵니다. 게이트웨이가 인증되지 않은 에이전트를 거부하는 것입니다.",
    "These products refuse plain HTTP. Give the gateway an HTTPS address first, then add it the same way.": "이 제품들은 일반 HTTP를 거부합니다. 먼저 게이트웨이에 HTTPS 주소를 준 뒤 같은 방식으로 추가하세요.",
    "Put HTTPS in front of it": "앞에 HTTPS 두기", "Quickest for a demo, a Cloudflare quick tunnel on the server:": "데모에 가장 빠른 방법은 서버의 Cloudflare 퀵 터널입니다:",
    "The printed address plus /mcp is the connector URL. It changes every restart and is open to anyone who has it. For a stable URL, terminate TLS with nginx and proxy to this port, with proxy_buffering off.": "출력된 주소에 /mcp를 붙인 것이 커넥터 URL입니다. 재시작마다 바뀌고 주소를 아는 누구에게나 열려 있습니다. 안정적인 URL이 필요하면 nginx로 TLS를 종단하고 이 포트로 프록시하되 proxy_buffering을 끄세요.",
    "Then set that address here with Edit connection, so these instructions and any new tokens use it.": "그런 다음 연결 편집으로 그 주소를 여기에 설정하면 이 안내와 새 토큰이 그 주소를 사용합니다.",
    "Copy this endpoint": "이 엔드포인트 복사", "This exact URL, including the /mcp path. The root path serves nothing and shows Not found.": "/mcp 경로를 포함한 이 URL 그대로입니다. 루트 경로는 아무것도 제공하지 않고 찾을 수 없음을 표시합니다.",
    "Add it in claude.ai": "claude.ai에 추가", "Settings, then Connectors, then Add custom connector. Paste the URL, give it a name, and click Add. It appears in the chat's tool menu.": "설정 → 커넥터 → 사용자 지정 커넥터 추가. URL을 붙여넣고 이름을 정한 뒤 추가를 누르세요. 채팅의 도구 메뉴에 나타납니다.",
    "Add it in ChatGPT": "ChatGPT에 추가", "Settings, then Connectors, then Add. Paste the same URL. Requires a plan that allows custom connectors.": "설정 → 커넥터 → 추가. 같은 URL을 붙여넣으세요. 사용자 지정 커넥터를 허용하는 플랜이 필요합니다.",
    "Ask for something": "무언가 요청해 보기", "Copilot Studio and Agentforce": "Copilot Studio와 Agentforce",
    "Both support remote MCP servers and need the same public HTTPS address and OAuth login as the cloud chat products.": "둘 다 원격 MCP 서버를 지원하며 클라우드 채팅 제품과 같은 공개 HTTPS 주소와 OAuth 로그인이 필요합니다.",
    "Same endpoint for every client below. Open the one you use;": "아래 모든 클라이언트에 같은 엔드포인트입니다. 사용하는 것을 여세요.",
    "at the top prints a ready-to-paste version with a token.": "(상단)은 토큰이 포함된 붙여넣기용 버전을 출력합니다.",
    "Claude Desktop runs on your own machine, so it either connects to this gateway over the network or starts its own copy locally. Pick one of the two entries below.": "Claude Desktop은 내 컴퓨터에서 실행되므로 네트워크로 이 게이트웨이에 연결하거나 로컬 복사본을 직접 실행합니다. 아래 둘 중 하나를 고르세요.",
    "Replace the directory with the path to the project on the machine running Claude Desktop. This value is where the portal's own server keeps it. No agent token is needed, because identity comes from the config.": "디렉터리를 Claude Desktop이 실행되는 컴퓨터의 프로젝트 경로로 바꾸세요. 이 값은 포털 서버가 보관하는 경로입니다. 신원이 설정에서 오므로 에이전트 토큰은 필요 없습니다.",
    "No credential is required because the agent-token requirement is switched off on the Security page.": "보안 페이지에서 에이전트 토큰 요구가 꺼져 있어 자격 증명이 필요 없습니다.",
  });
  Object.assign(dict, {
    "What to prepare": "준비할 것", "a value I type in": "직접 입력한 값", "Fixed value": "고정값", "the value to send": "보낼 값", "field, e.g. id": "필드, 예: id", "Filled in from the signed-in user": "로그인한 사용자 정보로 자동 입력",
    "This backend's tools take no company parameter, so nothing is filled in automatically.": "이 백엔드의 도구에는 회사 매개변수가 없어 자동으로 채우는 값이 없습니다.", "inherited": "상속됨",
    "A workflow is a fixed sequence of this backend's tools published as one extra tool, on every gateway that serves the backend. The model may use it or call the tools itself.": "워크플로는 이 백엔드 도구들의 고정된 순서를 하나의 추가 도구로 공개한 것으로, 이 백엔드를 제공하는 모든 게이트웨이에 나타납니다. 모델은 이를 사용할 수도, 도구를 직접 호출할 수도 있습니다.",
    "A workflow is a fixed sequence of tools published as one extra tool. The gateway runs the steps in order; the model may use it or call the tools itself. Workflows defined on a backend's page appear here too.": "워크플로는 도구들의 고정된 순서를 하나의 추가 도구로 공개한 것입니다. 게이트웨이가 단계를 순서대로 실행하며, 모델은 이를 사용할 수도 도구를 직접 호출할 수도 있습니다. 백엔드 페이지에서 정의한 워크플로도 여기에 나타납니다.", "Workflows": "워크플로", "New workflow": "새 워크플로", "Tool the model sees": "모델이 보는 도구", "Inputs": "입력", "Steps, in order": "단계 (순서대로)",
    "No workflows yet": "아직 워크플로가 없습니다", "Parameter values for this gateway": "이 게이트웨이의 매개변수 값", "Value here": "여기 값", "Backend's own": "백엔드 설정", "Save values": "값 저장",
    "Where each parameter's value comes from": "각 매개변수 값의 출처", "Which tool produces which id": "어떤 도구가 어떤 ID를 만드는지", "Comes from": "출처", "Observed": "관찰됨",
    "Confirmed": "확인됨", "Seen, not confirmed": "관찰됨, 미확인", "Add a row by hand": "직접 행 추가", "Add an override": "재정의 추가", "inherited": "상속", "cleared here": "여기서 해제", "overridden here": "여기서 재정의",
    "Fixed value, hidden from the model": "고정값, 모델에게 숨김", "Default, used when the model leaves it out": "기본값, 모델이 생략하면 사용", "Shown to the model as the default": "모델에게 기본값으로 표시", "Hidden from the model, sent on every call": "모델에게 숨기고 호출마다 전송",
    "Save workflow": "워크플로 저장", "Workflow saved": "워크플로 저장됨", "Workflow removed": "워크플로 제거됨", "Values saved": "값 저장됨", "Add step": "단계 추가",
    "A workflow is a fixed sequence of tools published as one tool. The gateway runs the steps in order, so the model cannot get the order wrong.": "워크플로는 도구 하나로 공개되는 고정된 도구 순서입니다. 게이트웨이가 단계를 순서대로 실행하므로 모델이 순서를 틀릴 수 없습니다.",
    "Overrides the backends' own settings, for this team only": "이 팀에만 적용되는 백엔드 설정 재정의", "Guidance for the model": "모델을 위한 안내", "How to use this backend": "이 백엔드 사용 방법",
    "Parameters filled in from the caller": "호출자 정보로 채우는 매개변수", "Save guidance": "안내 저장", "Guidance saved": "안내 저장됨",
    "Usage notes set": "사용 안내 설정됨", "No usage notes": "사용 안내 없음", "Parameter": "매개변수", "Used by": "사용 도구", "Value": "값",
    "Asked from the model": "모델에게 물음", "Instructions for the model": "모델을 위한 지침", "What the model is told": "모델이 받는 안내", "Preview as": "미리보기 대상",
    "a caller with no token": "토큰 없는 호출자", "Hidden from the model, filled on every call": "모델에게 숨기고 호출마다 채움",
    "Sent to the model when it connects, on every gateway that serves this backend. Say which tool to call first and which next, in plain steps, and what never to ask the user for.": "모델이 연결할 때, 이 백엔드를 제공하는 모든 게이트웨이에서 전달됩니다. 어떤 도구를 먼저, 어떤 도구를 다음에 호출할지 단계로 적고, 사용자에게 묻지 말아야 할 것을 적으세요.",
    "A parameter bound to the caller's identity disappears from the tools and is filled in by the gateway, whatever the model sends. The model can no longer pick the wrong company or person.": "호출자 신원에 묶인 매개변수는 도구에서 사라지고, 모델이 무엇을 보내든 게이트웨이가 채웁니다. 모델이 잘못된 회사나 사람을 고를 수 없습니다.",
    "Applies on the next connection. A caller with no token has no identity to fill in, so they keep seeing the parameter.": "다음 연결부터 적용됩니다. 토큰이 없는 호출자는 채울 신원이 없으므로 매개변수가 계속 보입니다.",
    "The opening lines a model reads when it connects here: who it is helping and how the backends fit together. Each backend's own usage notes are added underneath.": "모델이 여기에 연결할 때 처음 읽는 내용입니다. 누구를 돕는지, 백엔드들이 어떻게 맞물리는지 적으세요. 각 백엔드의 사용 안내가 그 아래에 붙습니다.",
    "Add instructions above, or usage notes on a backend's page. Without them a model has only tool names and descriptions to go on.": "위에 지침을 추가하거나 백엔드 페이지에서 사용 안내를 추가하세요. 없으면 모델은 도구 이름과 설명만 보고 판단합니다.",
    "This backend's tools take no parameters.": "이 백엔드의 도구에는 매개변수가 없습니다.", "Refresh tools once to read this server's parameter names.": "도구 새로고침을 한 번 실행하면 이 서버의 매개변수 이름을 읽습니다.", "Sign-in log": "로그인 로그", "Registered MCP clients": "등록된 MCP 클라이언트", "Recent steps": "최근 단계",
    "Client": "클라이언트", "Client id": "클라이언트 ID", "Sends users back to": "사용자 복귀 주소", "Registered": "등록 시각", "Step": "단계", "Client software": "클라이언트 소프트웨어",
    "No client has registered yet": "아직 등록된 클라이언트가 없습니다", "Nothing yet": "아직 없음",
    "Every step an MCP client takes at the gateway's sign-in endpoints (discovery, registration, the sign-in page, token exchange) and every call the gateway refused. When a connector says it could not reach the gateway, the last lines here say how far it got.": "MCP 클라이언트가 게이트웨이 로그인 엔드포인트에서 거친 모든 단계(검색, 등록, 로그인 페이지, 토큰 교환)와 게이트웨이가 거부한 모든 호출입니다. 커넥터가 게이트웨이에 연결할 수 없다고 하면 여기 마지막 줄들이 어디까지 갔는지 알려줍니다.",
    "claude.ai and ChatGPT register themselves the first time someone adds a gateway that requires a token.": "claude.ai와 ChatGPT는 토큰이 필요한 게이트웨이를 처음 추가할 때 스스로 등록합니다.",
    "Steps appear as soon as a client discovers the sign-in or the gateway refuses a call.": "클라이언트가 로그인을 검색하거나 게이트웨이가 호출을 거부하면 단계가 표시됩니다.", "Gateways this token opens": "이 토큰으로 열리는 게이트웨이", "Shared gateway": "공유 게이트웨이",
    "No named gateway admits this person yet, so the shared endpoint is shown.": "아직 이 사람을 허용하는 이름 있는 게이트웨이가 없어 공유 엔드포인트를 표시합니다.", "Sign in when asked": "요청 시 로그인", "MCP clients sign in with OAuth 2.1": "MCP 클라이언트가 OAuth 2.1로 로그인",
    "This endpoint is public HTTPS and asks callers to sign in. Both products discover the gateway's own OAuth sign-in on their own: paste the URL, sign in with your employee account when the portal's page opens, and every call is made as you.": "이 엔드포인트는 공개 HTTPS이며 호출자에게 로그인을 요구합니다. 두 제품 모두 게이트웨이의 자체 OAuth 로그인을 스스로 찾습니다. URL을 붙여넣고, 포털 페이지가 열리면 직원 계정으로 로그인하세요. 이후 모든 호출은 본인으로 이루어집니다.",
    "Right after you add the connector, the portal's sign-in page opens. Use your employee email and password (members only, not the admin account). The connector then holds a token bound to you, renewed automatically and listed on the Agent Tokens page, where it can be revoked.": "커넥터를 추가하면 바로 포털 로그인 페이지가 열립니다. 직원 이메일과 비밀번호를 사용하세요(관리자 계정이 아닌 멤버만). 커넥터는 본인에게 묶인 토큰을 갖게 되며, 자동으로 갱신되고 에이전트 토큰 페이지에 표시되어 폐기할 수 있습니다.",
    "The gateway is its own authorization server (PKCE, dynamic client registration, refresh tokens); identities come from the user directory. Production: federate the sign-in page to Bizplay SSO.": "게이트웨이가 자체 인가 서버입니다(PKCE, 동적 클라이언트 등록, 리프레시 토큰). 신원은 사용자 디렉터리에서 옵니다. 운영 환경: 로그인 페이지를 Bizplay SSO에 연동.",
    "Both support remote MCP servers and use the same public HTTPS address and the gateway's own OAuth sign-in as the cloud chat products.": "둘 다 원격 MCP 서버를 지원하며 클라우드 채팅 제품과 같은 공개 HTTPS 주소와 게이트웨이 자체 OAuth 로그인을 사용합니다.", "policy is edited on each backend's page": "정책은 각 백엔드 페이지에서 편집",
    "Register the endpoint in the Agentforce MCP registry, then grant the agent access to the tools you enabled for this API.": "Agentforce MCP 레지스트리에 엔드포인트를 등록한 뒤, 이 API에서 활성화한 도구에 에이전트 접근 권한을 주세요.",
    "A hosted gateway with a certificate, OAuth mapped to the customer's identity provider, and an agent token policy per company. The Security page tracks what is still open.": "인증서가 있는 호스팅 게이트웨이, 고객의 ID 제공자에 연결된 OAuth, 회사별 에이전트 토큰 정책. 남은 항목은 보안 페이지에서 추적합니다.",
  });
  rules.push(
    [/^Add the gateway as a custom connector, point it at (.+) on its public address, then enable it as a tool for the agent\.$/, "게이트웨이를 사용자 지정 커넥터로 추가하고 공개 주소의 $1 을 가리키게 한 뒤, 에이전트의 도구로 활성화하세요."],
    [/^Who can use (.+)$/, "$1을(를) 사용할 수 있는 사람"], [/^from (.+)$/, "$1에서"], [/^Workflows of (.+)$/, "$1의 워크플로"],
    [/^(\d+) parameter\(s\) filled in$/, "매개변수 $1개 자동 입력"], [/^(\d+) other parameter\(s\)$/, "기타 매개변수 $1개"],
    [/^Filled with (.+)$/, "$1(으)로 채움"], [/^Looks like (.+)$/, "$1(으)로 보임"],
    [/^Registered backends, (\d+) published$/, "등록된 백엔드, $1개 게시됨"], [/^Gateway calls, last 14 days · (\d+) denied, (\d+) errors$/, "게이트웨이 호출, 최근 14일 · 거부 $1, 오류 $2"],
    [/^Security score, (\d+) open item\(s\)$/, "보안 점수, 미완료 $1개"], [/^Accepted risk, demo data only: (.+)$/, "수용된 위험, 데모 데이터 전용: $1"],
    [/^Unconfirmed: (.+)$/, "미확인: $1"], [/^Comma separated\. In use: (.+)\.$/, "쉼표로 구분. 사용 중: $1."],
    [/^Comma separated\. A caller needs any one of them on their agent token\. In use: (.+)\.$/, "쉼표로 구분. 호출자의 에이전트 토큰에 그중 하나가 있어야 합니다. 사용 중: $1."],
    [/^Gateway -> (.+) service token$/, "게이트웨이 → $1 서비스 토큰"], [/^Gateway -> (.+) service account$/, "게이트웨이 → $1 서비스 계정"],
    [/^signs in as (.+)$/, "로그인 계정: $1"], [/^Serve this backend alone at (.+)$/, "이 백엔드를 $1 에서 단독 제공"], [/^Stop serving (.+)$/, "$1 제공 중단"],
    [/^Reachable only from (.+)\.$/, "$1 에서만 접근 가능."], [/^Each caller's own linked account token is sent; (\d+) user\(s\) linked\.$/, "호출자마다 자신의 연결 계정 토큰이 전송됩니다. 사용자 $1명 연결됨."],
    [/^The gateway signs in with each caller's own credentials; (\d+) user\(s\) connected\.$/, "게이트웨이가 호출자마다 자신의 자격 증명으로 로그인합니다. 사용자 $1명 연결됨."],
    [/^Spec from (.+?)\. Registered by (.+?) on (.+?)\. (.*)$/, (m, src, who, when, rest) => `스펙 출처: ${src}. ${who}이(가) ${when}에 등록. ${t(rest)}`],
    [/^Tools proxied from the MCP server, unchanged\. Registered by (.+?) on (.+?)\. (.*)$/, (m, who, when, rest) => `MCP 서버에서 그대로 프록시된 도구. ${who}이(가) ${when}에 등록. ${t(rest)}`],
    [/^This gateway accepts anonymous callers, so one line with no token connects Claude Code to (.+)\.$/, "이 게이트웨이는 익명 호출자를 받으므로 토큰 없는 한 줄로 Claude Code를 $1 에 연결합니다."],
    [/^This endpoint is (.+), so it only works if Claude Desktop runs on the same machine as the gateway\. Use Edit connection to set the address other machines can reach\.$/, "이 엔드포인트는 $1 이므로 Claude Desktop이 게이트웨이와 같은 컴퓨터에서 실행될 때만 동작합니다. 다른 컴퓨터가 접근할 주소는 연결 편집에서 설정하세요."],
  );

  const ATTRS = ["placeholder", "title", "aria-label"];
  // The stored choice wins; a first visit follows the browser language.
  let lang = (navigator.language || "").toLowerCase().startsWith("ko") ? "ko" : "en";
  try { const stored = localStorage.getItem("portal.lang"); if (stored === "ko" || stored === "en") lang = stored; } catch {}

  function t(text) {
    if (lang !== "ko" || !text) return text;
    const trimmed = text.trim();
    if (!trimmed) return text;
    const hit = dict[trimmed];
    if (hit) return text.replace(trimmed, hit);
    for (const [re, rep] of rules) if (re.test(trimmed)) return text.replace(trimmed, trimmed.replace(re, rep));
    return text;
  }

  function translate(root) {
    if (lang !== "ko" || !root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.parentElement && /^(SCRIPT|STYLE|PRE|CODE)$/.test(n.parentElement.tagName)) || !n.nodeValue.trim() ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
    });
    const nodes = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) nodes.push(n);
    for (const n of nodes) { const v = t(n.nodeValue); if (v !== n.nodeValue) n.nodeValue = v; }
    const scope = root.nodeType === 1 ? [root, ...root.querySelectorAll("[placeholder],[title],[aria-label]")] : [...root.querySelectorAll("[placeholder],[title],[aria-label]")];
    for (const el of scope) for (const a of ATTRS) { const v = el.getAttribute?.(a); if (v) { const w = t(v); if (w !== v) el.setAttribute(a, w); } }
  }

  function setLang(next) {
    try { localStorage.setItem("portal.lang", next); } catch {}
    location.reload();
  }

  function watch() {
    if (lang !== "ko") return;
    document.documentElement.lang = "ko";
    translate(document.body);
    let queued = false;
    const observer = new MutationObserver((records) => {
      if (queued) return;
      queued = true;
      queueMicrotask(() => { queued = false; for (const r of records) for (const n of r.addedNodes) translate(n.nodeType === 3 ? n.parentElement : n); });
    });
    observer.observe(document.body, { childList: true, subtree: true });
    const nativeConfirm = window.confirm.bind(window);
    window.confirm = (msg) => nativeConfirm(t(msg));
  }

  return { t, translate, setLang, watch, get lang() { return lang; } };
})();
