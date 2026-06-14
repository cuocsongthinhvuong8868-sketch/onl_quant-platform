import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
import logging

from tools.sentiment_factor_news.config import DATA_DIR

logger = logging.getLogger(__name__)

def run_cmd(cmd: list[str], cwd: Path):
    try:
        res = subprocess.run(
            cmd,
            cwd=cwd,
            shell=False,
            text=True,
            capture_output=True,
            check=False,
        )
        return res
    except Exception as e:
        # Create a dummy result object mimicking completed process
        class DummyProcess:
            returncode = -1
            stdout = ""
            stderr = str(e)
        return DummyProcess()

def publish_feed(repo_path: str, branch: str = "main", remote: str = "origin") -> dict:
    """
    Commit and push the feed files inside data_lake/sentiment_factor_news/feed/.
    Only commits if changes exist.
    """
    repo = Path(repo_path).resolve()
    feed_path = (DATA_DIR / "feed").resolve()
    try:
        feed_git_path = str(feed_path.relative_to(repo))
    except ValueError:
        feed_git_path = str(feed_path)
    logger.info(f"Publishing feed to git repo at {repo} on branch {branch}")
    
    if not (repo / ".git").exists():
        logger.warning(f"No git repository found at {repo}. Skipping git publish.")
        return {"published": False, "reason": "no_git_repo"}
        
    # Checkout branch
    checkout = run_cmd(["git", "checkout", branch], repo)
    if checkout.returncode != 0:
        logger.warning(f"Could not checkout branch {branch}. Attempting to proceed anyway. Stderr: {checkout.stderr}")
        
    # Stage sentiment feed directory
    add = run_cmd(["git", "add", feed_git_path], repo)
    if add.returncode != 0:
        logger.error(f"Failed to git add feed files. Stderr: {add.stderr}")
        return {"published": False, "reason": "git_add_failed"}
        
    # Check status
    status = run_cmd(["git", "status", "--porcelain", feed_git_path], repo)
    if not status.stdout.strip():
        logger.info("No changes in feed files. Skipping commit and push.")
        return {"published": False, "reason": "no_changes"}
        
    # Commit
    vn_tz = timezone(timedelta(hours=7))
    time_str = datetime.now(vn_tz).strftime("%Y-%m-%d %H:%M")
    msg = f"update market sentiment feed: {time_str}"
    
    commit = run_cmd(["git", "commit", "-m", msg], repo)
    if commit.returncode != 0:
        logger.error(f"Git commit failed: {commit.stderr}")
        return {"published": False, "reason": "commit_failed"}
        
    # Push
    push = run_cmd(["git", "push", remote, branch], repo)
    if push.returncode != 0:
        logger.error(f"Git push failed: {push.stderr}")
        return {
            "published": False,
            "reason": "push_failed",
            "stderr": push.stderr[-1000:]
        }
        
    logger.info("Successfully pushed feed updates to remote git repository.")
    return {
        "published": True,
        "commit_returncode": commit.returncode,
        "push_returncode": push.returncode,
        "stdout": push.stdout,
        "stderr": push.stderr
    }
