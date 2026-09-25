from pathlib import Path

from .logger import LogManager, StructuredLogger

# server_config에서 로그 디렉토리 설정 가져오기 (server 폴더 기준 상대 경로)
log_dir = "logs"

# server 폴더 기준으로 절대 경로 변환
# server/log/__init__.py에서 server 폴더로 이동
server_dir = Path(__file__).resolve().parent
log_directory = str(server_dir / log_dir)

# 디렉토리가 없으면 생성
Path(log_directory).mkdir(parents=True, exist_ok=True)

log_manager = LogManager(directory=log_directory)
app_logger = StructuredLogger(log_manager.logger)

__all__ = ["app_logger", "log_manager"]
