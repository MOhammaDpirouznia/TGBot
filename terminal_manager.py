import subprocess
import logging
import asyncio
import time
import os
from typing import Dict, Any, Tuple
try:
    import paramiko
except ImportError:
    paramiko = None

logger = logging.getLogger(__name__)

class TerminalManager:
    """مدیریت اجرای دستورات خط فرمان به صورت لوکال و ریموت (SSH)"""
    
    @staticmethod
    def run_local_command(command: str, timeout: int = 15) -> Tuple[bool, str]:
        """
        اجرای یک دستور در سرور لوکال (سروری که ربات روی آن ران است)
        """
        # Block dangerous interactive commands
        blocked_cmds = ["nano", "vi", "vim", "top", "htop", "less", "more", "tail -f"]
        cmd_lower = command.lower().strip()
        if any(cmd_lower.startswith(b) for b in blocked_cmds) or "&&" in cmd_lower or "|" in cmd_lower:
            if any(cmd_lower.startswith(b) for b in blocked_cmds):
                return False, "⚠️ اجرای دستورات تعاملی (Interactive) مانند nano, top در این ترمینال مجاز نیست."

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            output = result.stdout
            if result.stderr:
                output += f"\n[Errors/Warnings]:\n{result.stderr}"
                
            if not output.strip():
                output = "[بدون خروجی / دستور با موفقیت اجرا شد]"
                
            return (result.returncode == 0), output.strip()
            
        except subprocess.TimeoutExpired:
            return False, f"⚠️ تایم‌اوت: اجرای دستور بیش از {timeout} ثانیه طول کشید و متوقف شد."
        except Exception as e:
            return False, f"❌ خطای سیستم در اجرای دستور:\n{e}"

    @staticmethod
    def run_remote_command(host: str, port: int, user: str, password: str, command: str, timeout: int = 15) -> Tuple[bool, str]:
        """
        اجرای یک دستور در سرور ریموت از طریق SSH
        """
        if not paramiko:
            return False, "❌ کتابخانه paramiko نصب نیست. برای اتصال SSH باید نصب شود."
            
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            client.connect(
                hostname=host,
                port=port,
                username=user,
                password=password,
                timeout=5
            )
            
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
            
            end_time = time.time() + timeout
            while not stdout.channel.exit_status_ready():
                if time.time() > end_time:
                    return False, f"⚠️ تایم‌اوت: اجرای دستور بیش از {timeout} ثانیه طول کشید."
                time.sleep(0.5)
                
            out = stdout.read().decode('utf-8', errors='replace').strip()
            err = stderr.read().decode('utf-8', errors='replace').strip()
            
            output = out
            if err:
                output += f"\n[Errors/Warnings]:\n{err}"
                
            if not output.strip():
                output = "[بدون خروجی / دستور با موفقیت اجرا شد]"
                
            return True, output
            
        except paramiko.AuthenticationException:
            return False, "❌ خطای احراز هویت (نام کاربری یا رمز عبور اشتباه است)"
        except paramiko.SSHException as ssh_err:
            return False, f"❌ خطای اتصال SSH:\n{ssh_err}"
        except Exception as e:
            return False, f"❌ خطای ناشناخته:\n{e}"
        finally:
            client.close()
