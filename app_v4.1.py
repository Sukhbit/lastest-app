import sys
import os
import math
import shutil
import requests
import subprocess
import json
import threading
import time
import socket
import platform
import getpass
import re
import io
import gc
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
import gpxpy
from xml.etree import ElementTree as ET
from botocore.exceptions import ClientError, BotoCoreError
from boto3.s3.transfer import TransferConfig
from dotenv import load_dotenv
from pymediainfo import MediaInfo
import psutil
import backoff
from datetime import datetime, timedelta
import pytz
import dateutil.parser
import xml.etree.ElementTree as ET

from PyQt6.QtCore import (Qt, QThread, pyqtSignal, QTimer, QDateTime, 
                         QPropertyAnimation, QEasingCurve, QPoint, QRect, 
                         QParallelAnimationGroup)
from PyQt6.QtGui import (QFont, QPixmap, QIcon, QStandardItemModel, 
                        QStandardItem)
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox, 
                            QToolButton, QLineEdit, QDialog, QDialogButtonBox,
                            QLabel, QMessageBox, QScrollArea, QFrame, 
                            QTextEdit, QPushButton, QCheckBox, QGridLayout,
                            QTreeWidget, QTreeWidgetItem, QHeaderView, QSizePolicy,
                            QSplitter, QListWidget, QListWidgetItem, QSpinBox,
                            QGroupBox, QProgressBar, QApplication, QFileDialog,
                            QTabWidget, QMainWindow, QCompleter)

# ---------------- CONFIG ----------------
VIDEO_FILE_FORMATS = [".mp4", ".mov", ".avi", ".mkv", ".np4"]
EXIFTOOL_PATH = "/usr/bin/exiftool"
FFMPEG_PATH = os.getenv('FFMPEG_PATH', 'ffmpeg')
# Optional: path to libmediainfo shared library. If set, pymediainfo will try it first.
MEDIAINFO_LIBRARY_PATH = os.getenv('MEDIAINFO_LIBRARY_PATH', '')
def write_to_file_log(message, level="INFO"):
    """Global logging helper to avoid NameError crashes"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")
    except Exception:
        pass

# ---------------- BULK ROAD CREATION CONFIG ----------------
HEADERS = {"Security-Password": "admin@123"}


# ---------------- INTERNET MONITORING ----------------
class InternetMonitor(QThread):
    """Thread for monitoring internet connection and speed"""
    status_signal = pyqtSignal(bool, str)
    speed_signal = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.running = True
        self.last_bytes_sent = psutil.net_io_counters().bytes_sent
        self.last_bytes_recv = psutil.net_io_counters().bytes_recv
        self.last_time = time.time()

    def run(self):
        while self.running:
            try:
                # Check internet connection
                is_connected = self.check_connection()
                if is_connected:
                    status_text = "Connected"
                    # Calculate real-time speed
                    current_bytes_sent = psutil.net_io_counters().bytes_sent
                    current_bytes_recv = psutil.net_io_counters().bytes_recv
                    current_time = time.time()
                    
                    elapsed = current_time - self.last_time
                    if elapsed >= 1.0:
                        up_speed = (current_bytes_sent - self.last_bytes_sent) / elapsed / (1024 * 1024) * 8
                        down_speed = (current_bytes_recv - self.last_bytes_recv) / elapsed / (1024 * 1024) * 8
                        
                        self.speed_signal.emit(f"UP: {up_speed:.1f} Mbps | DOWN: {down_speed:.1f} Mbps")
                        
                        self.last_bytes_sent = current_bytes_sent
                        self.last_bytes_recv = current_bytes_recv
                        self.last_time = current_time
                else:
                    status_text = "Check Connection"
                    self.speed_signal.emit("Network: --/-- Mbps")
                
                self.status_signal.emit(is_connected, status_text)
                
            except Exception as e:
                # Print to stdout for debugging but don't crash
                print(f"Internet monitoring inner error: {e}")
                
            # Use small sleeps to keep UI thread snappy
            for _ in range(10):
                if not self.running: break
                time.sleep(0.1)

    def check_connection(self):
        """Check if internet connection is available"""
        try:
            # Try to connect to a reliable host
            socket.create_connection(("8.8.8.8", 53), timeout=2)
            return True
        except OSError:
            return False

    def stop(self):
        self.running = False

# ---------------- HTML LOG GENERATOR ----------------
class HTMLLogGenerator:
    """Generate HTML logs with color-coded messages and enhanced formatting"""
    
    @staticmethod
    def create_html_log(log_data, output_path=None):
        """Create an HTML log file from log data"""
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = Path.cwd() / "logs" / f"session_log_{timestamp}.html"
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        html_content = HTMLLogGenerator.generate_html_content(log_data)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return output_path
    
    @staticmethod
    def generate_html_content(log_data):
        """Generate HTML content with styling"""
        username = log_data.get('username', 'Unknown')
        survey_id = log_data.get('survey_id', 'Unknown')
        survey_name = log_data.get('survey_name', 'Unknown Survey')
        start_time = log_data.get('start_time', datetime.now().isoformat())
        system_info = log_data.get('system_info', {})
        log_entries = log_data.get('entries', [])
        
        # Extract time settings from log_data with proper defaults
        time_settings = log_data.get('time_settings', {})
        time_option = time_settings.get('time_option', 'Not specified')
        start_buffer = time_settings.get('start_buffer', 'Not specified')
        end_buffer = time_settings.get('end_buffer', 'Not specified')
        
        # Extract road IDs and model type from log_data
        road_ids = log_data.get('road_ids', [])
        model_type = log_data.get('model_type', 'Not specified')
        
        # Sort road IDs and format them for display
        sorted_road_ids = sorted(road_ids)
        road_ids_display = ', '.join(map(str, sorted_road_ids)) if sorted_road_ids else 'No roads processed'
        
        # Determine if this is an S3 upload session by checking log entries
        is_s3_upload = any('S3 upload' in entry.get('message', '') for entry in log_entries)
        has_uploaded_videos = any('uploaded videos' in entry.get('message', '').lower() for entry in log_entries)
        
        # HTML template with modern styling
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RoadAthena Session Log - {username}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        
        .header {{
            background: linear-gradient(135deg, #2c3e50, #3498db);
            color: white;
            padding: 30px;
            text-align: center;
        }}
        
        .header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            font-weight: 300;
        }}
        
        .header .subtitle {{
            font-size: 1.1em;
            opacity: 0.9;
            margin-bottom: 20px;
        }}
        
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }}
        
        .info-card {{
            background: rgba(255,255,255,0.1);
            padding: 15px;
            border-radius: 10px;
            backdrop-filter: blur(10px);
        }}
        
        .info-card h3 {{
            font-size: 0.9em;
            opacity: 0.8;
            margin-bottom: 5px;
        }}
        
        .info-card p {{
            font-size: 1.1em;
            font-weight: 500;
        }}
        
        .time-settings-section {{
            background: #f8f9fa;
            padding: 20px;
            margin: 20px 30px;
            border-radius: 10px;
            border-left: 4px solid #3498db;
        }}
        
        .time-settings-title {{
            font-size: 1.2em;
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 15px;
        }}
        
        .time-settings-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        
        .time-setting-item {{
            background: white;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #e9ecef;
        }}
        
        .time-setting-label {{
            font-size: 0.9em;
            color: #6c757d;
            margin-bottom: 5px;
        }}
        
        .time-setting-value {{
            font-size: 1.1em;
            font-weight: 600;
            color: #2c3e50;
        }}
        
        .road-info-section {{
            background: #e8f5e8;
            padding: 20px;
            margin: 20px 30px;
            border-radius: 10px;
            border-left: 4px solid #27ae60;
        }}
        
        .road-info-title {{
            font-size: 1.2em;
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 15px;
        }}
        
        .road-info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
        }}
        
        .road-info-item {{
            background: white;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #d4edda;
        }}
        
        .road-info-label {{
            font-size: 0.9em;
            color: #6c757d;
            margin-bottom: 5px;
        }}
        
        .road-info-value {{
            font-size: 1.1em;
            font-weight: 600;
            color: #155724;
        }}
        
        .road-ids-list {{
            background: white;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #d4edda;
            max-height: 200px;
            overflow-y: auto;
        }}
        
        .road-ids-title {{
            font-size: 0.9em;
            color: #6c757d;
            margin-bottom: 10px;
        }}
        
        .road-ids-content {{
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
            color: #155724;
            line-height: 1.4;
        }}
        
        .upload-status {{
            margin-top: 10px;
            padding: 10px 15px;
            background: #d4edda;
            border: 1px solid #c3e6cb;
            border-radius: 6px;
            font-size: 0.9em;
            color: #155724;
        }}
        
        .upload-status.warning {{
            background: #fff3cd;
            border-color: #ffeaa7;
            color: #856404;
        }}
        
        .log-section {{
            padding: 30px;
        }}
        
        .log-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 2px solid #e9ecef;
        }}
        
        .log-title {{
            font-size: 1.5em;
            color: #2c3e50;
            font-weight: 600;
        }}
        
        .log-entries {{
            max-height: 600px;
            overflow-y: auto;
            border: 1px solid #e9ecef;
            border-radius: 10px;
            padding: 0;
        }}
        
        .log-entry {{
            padding: 15px 20px;
            border-bottom: 1px solid #f8f9fa;
            display: flex;
            align-items: flex-start;
            gap: 15px;
        }}
        
        .log-entry:last-child {{
            border-bottom: none;
        }}
        
        .log-entry:hover {{
            background: #f8f9fa;
        }}
        
        .timestamp {{
            color: #6c757d;
            font-size: 0.85em;
            min-width: 120px;
            font-family: 'Courier New', monospace;
        }}
        
        .level {{
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: 600;
            text-transform: uppercase;
            min-width: 80px;
            text-align: center;
        }}
        
        .level-info {{
            background: #d1ecf1;
            color: #0c5460;
        }}
        
        .level-success {{
            background: #d4edda;
            color: #155724;
        }}
        
        .level-warning {{
            background: #fff3cd;
            color: #856404;
        }}
        
        .level-error {{
            background: #f8d7da;
            color: #721c24;
        }}
        
        .message {{
            flex: 1;
            font-size: 0.95em;
            line-height: 1.5;
            word-wrap: break-word;
        }}
        
        .stats {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            margin-top: 20px;
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        
        .stat-item {{
            text-align: center;
            padding: 15px;
        }}
        
        .stat-number {{
            font-size: 2em;
            font-weight: bold;
            color: #3498db;
        }}
        
        .stat-label {{
            font-size: 0.9em;
            color: #6c757d;
            margin-top: 5px;
        }}
        
        .footer {{
            background: #2c3e50;
            color: white;
            text-align: center;
            padding: 20px;
            font-size: 0.9em;
        }}
        
        /* Scrollbar styling */
        .log-entries::-webkit-scrollbar {{
            width: 8px;
        }}
        
        .log-entries::-webkit-scrollbar-track {{
            background: #f1f1f1;
            border-radius: 0 10px 10px 0;
        }}
        
        .log-entries::-webkit-scrollbar-thumb {{
            background: #c1c1c1;
            border-radius: 4px;
        }}
        
        .log-entries::-webkit-scrollbar-thumb:hover {{
            background: #a8a8a8;
        }}
        
        .road-ids-list::-webkit-scrollbar {{
            width: 6px;
        }}
        
        .road-ids-list::-webkit-scrollbar-track {{
            background: #f1f1f1;
            border-radius: 3px;
        }}
        
        .road-ids-list::-webkit-scrollbar-thumb {{
            background: #c1c1c1;
            border-radius: 3px;
        }}
        
        .road-ids-list::-webkit-scrollbar-thumb:hover {{
            background: #a8a8a8;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>RoadAthena Session Log</h1>
            <div class="subtitle">Professional Road Data Management System</div>
            <div class="info-grid">
                <div class="info-card">
                    <h3>User</h3>
                    <p>{username}</p>
                </div>
                <div class="info-card">
                    <h3>Survey Name</h3>
                    <p>{survey_name}</p>
                </div>
                <div class="info-card">
                    <h3>Survey ID</h3>
                    <p>{survey_id}</p>
                </div>
                <div class="info-card">
                    <h3>Start Time</h3>
                    <p>{start_time}</p>
                </div>
                <div class="info-card">
                    <h3>Platform</h3>
                    <p>{system_info.get('platform', 'Unknown')}</p>
                </div>
            </div>
        </div>
        
        <!-- Time Settings Section -->
        <div class="time-settings-section">
            <div class="time-settings-title">Time Settings Configuration</div>
            <div class="time-settings-grid">
                <div class="time-setting-item">
                    <div class="time-setting-label">Time Option</div>
                    <div class="time-setting-value">{time_option}</div>
                </div>
                <div class="time-setting-item">
                    <div class="time-setting-label">Start Buffer</div>
                    <div class="time-setting-value">{start_buffer} seconds</div>
                </div>
                <div class="time-setting-item">
                    <div class="time-setting-label">End Buffer</div>
                    <div class="time-setting-value">{end_buffer} seconds</div>
                </div>
            </div>
        </div>
        
        <!-- Road Information Section -->
        <div class="road-info-section">
            <div class="road-info-title">Road Processing Information</div>
            <div class="road-info-grid">
                <div class="road-info-item">
                    <div class="road-info-label">Model Type</div>
                    <div class="road-info-value">{model_type}</div>
                </div>
                <div class="road-info-item">
                    <div class="road-info-label">Total Roads Processed</div>
                    <div class="road-info-value">{len(sorted_road_ids)}</div>
                </div>"""
        
        # Add S3-specific information if this is an S3 upload session
        if is_s3_upload:
            html += f"""
                <div class="road-info-item">
                    <div class="road-info-label">S3 Upload Status</div>
                    <div class="road-info-value">Completed</div>
                </div>"""
        
        html += f"""
            </div>
            <div style="margin-top: 15px;">
                <div class="road-ids-list">
                    <div class="road-ids-title">"""
        
        # Dynamic title based on context
        if has_uploaded_videos:
            html += f"Road IDs with Uploaded Videos (Sorted):"
        else:
            html += f"Road IDs Processed (Sorted):"
        
        html += f"""</div>
                    <div class="road-ids-content">{road_ids_display}</div>
                </div>
            </div>"""
        
        # Add upload status message
        if has_uploaded_videos:
            html += f"""
            <div class="upload-status">
                ✅ Videos from these {len(sorted_road_ids)} roads were successfully uploaded to S3 and archived in uploaded_files_archive
            </div>"""
        elif is_s3_upload and not sorted_road_ids:
            html += f"""
            <div class="upload-status warning">
                ⚠️ No road IDs detected in uploaded files
            </div>"""
        
        html += f"""
        </div>
        
        <div class="log-section">
            <div class="log-header">
                <div class="log-title">Processing Log</div>
            </div>
            
            <div class="log-entries">"""
        
        # Add log entries
        for entry in log_entries:
            timestamp = entry.get('timestamp', '')
            level = entry.get('level', 'info')
            message = entry.get('message', '')
            
            # Convert level to CSS class
            level_class = f"level-{level}"
            
            html += f"""
                <div class="log-entry">
                    <div class="timestamp">{timestamp}</div>
                    <div class="level {level_class}">{level.upper()}</div>
                    <div class="message">{message}</div>
                </div>"""
        
        # Add statistics section
        info_count = len([e for e in log_entries if e.get('level') == 'info'])
        success_count = len([e for e in log_entries if e.get('level') == 'success'])
        warning_count = len([e for e in log_entries if e.get('level') == 'warning'])
        error_count = len([e for e in log_entries if e.get('level') == 'error'])
        total_count = len(log_entries)
        
        html += f"""
            </div>
            
            <div class="stats">
                <div class="stats-grid">
                    <div class="stat-item">
                        <div class="stat-number">{total_count}</div>
                        <div class="stat-label">Total Entries</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-number">{info_count}</div>
                        <div class="stat-label">Info Messages</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-number">{success_count}</div>
                        <div class="stat-label">Success Messages</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-number">{warning_count}</div>
                        <div class="stat-label">Warnings</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-number">{error_count}</div>
                        <div class="stat-label">Errors</div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="footer">
            Generated by RoadAthena Toolkit • {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>
    </div>
</body>
</html>"""
        
        return html
    

    

# ---------------- INTERNET MONITORING ----------------

# ---------------- UTILITIES ----------------
def get_system_info():
    """Get detailed system information"""
    try:
        system_info = {
            "username": getpass.getuser(),
            "hostname": socket.gethostname(),
            "platform": platform.system(),
            "platform_version": platform.version(),
            "processor": platform.processor(),
            "memory_gb": round(psutil.virtual_memory().total / (1024**3), 1),
            "cpu_cores": psutil.cpu_count(logical=False),
            "cpu_threads": psutil.cpu_count(logical=True),
            "python_version": platform.python_version()
        }
        return system_info
    except Exception as e:
        return {"error": f"Could not get system info: {e}"}

# ---------------- S3 BROWSER THREAD ----------------
class S3BrowserThread(QThread):
    """Thread for browsing S3 bucket contents with filtering support"""
    log_signal = pyqtSignal(str, str)
    data_loaded = pyqtSignal(list)
    finished_signal = pyqtSignal(bool, str)
    
    def __init__(self, s3_client, bucket_name, prefix="", max_keys=1000, filter_path=""):
        super().__init__()
        self.s3_client = s3_client
        self.bucket_name = bucket_name
        self.prefix = prefix
        self.max_keys = max_keys
        self.filter_path = filter_path  # New: filter path
        self.cancelled = False
        
    def run(self):
        try:
            if not self.s3_client:
                self.log_signal.emit("S3 client not available", "error")
                self.finished_signal.emit(False, "S3 client not available")
                return
                
            if self.filter_path and not self.prefix.startswith(self.filter_path):
                # If we have a filter path and current prefix doesn't match, adjust
                self.prefix = self.filter_path
                
            self.log_signal.emit(f"Loading S3 contents from: {self.prefix}", "info")
            items = self.list_s3_objects()
            self.data_loaded.emit(items)
            self.finished_signal.emit(True, f"Loaded {len(items)} items")
            
        except Exception as e:
            error_msg = f"Error browsing S3: {str(e)}"
            self.log_signal.emit(error_msg, "error")
            self.finished_signal.emit(False, error_msg)
    
    def cancel(self):
        self.cancelled = True
    
    def list_s3_objects(self):
        """List S3 objects with pagination support and filtering"""
        items = []
        try:
            paginator = self.s3_client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(
                Bucket=self.bucket_name,
                Prefix=self.prefix,
                Delimiter='/',
                PaginationConfig={'PageSize': self.max_keys}
            )
            
            for page in page_iterator:
                if self.cancelled:
                    break
                    
                # Process common prefixes (folders)
                if 'CommonPrefixes' in page:
                    for prefix in page['CommonPrefixes']:
                        folder_name = prefix['Prefix'].replace(self.prefix, '').rstrip('/')
                        
                        # Apply filter if specified
                        if self.filter_path and not prefix['Prefix'].startswith(self.filter_path):
                            continue
                            
                        items.append({
                            'name': folder_name,
                            'type': 'folder',
                            'path': prefix['Prefix'],
                            'size': 0,
                            'last_modified': '',
                            'icon': 'folder'
                        })
                
                # Process objects (files)
                if 'Contents' in page:
                    for obj in page['Contents']:
                        # Skip the folder itself
                        if obj['Key'] == self.prefix:
                            continue
                            
                        # Apply filter if specified
                        if self.filter_path and not obj['Key'].startswith(self.filter_path):
                            continue
                            
                        # Only show files in current directory (not subdirectories)
                        relative_path = obj['Key'].replace(self.prefix, '')
                        if '/' in relative_path and not relative_path.endswith('/'):
                            continue
                            
                        file_name = obj['Key'].split('/')[-1]
                        file_size = obj.get('Size', 0)
                        last_modified = obj.get('LastModified', '')
                        
                        # Determine file type and icon
                        file_type = 'file'
                        icon = 'file'
                        if file_name.lower().endswith(('.mp4', '.mov', '.avi', '.mkv')):
                            icon = 'video'
                        elif file_name.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                            icon = 'image'
                        elif file_name.lower().endswith(('.txt', '.log', '.json')):
                            icon = 'text'
                        elif file_name.lower().endswith(('.gpx', '.xml')):
                            icon = 'gpx'
                            
                        items.append({
                            'name': file_name,
                            'type': file_type,
                            'path': obj['Key'],
                            'size': file_size,
                            'last_modified': last_modified,
                            'icon': icon
                        })
                        
        except Exception as e:
            self.log_signal.emit(f"Error listing S3 objects: {str(e)}", "error")
            
        return items


# ---------------- LOGIN PAGE ----------------

class LoginPage(QDialog):
    login_successful = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_api_url = "https://app.roadathena.com/"
        self.auth_token = ""
        self.user_data = {}
        self.dash_url = None

        self.setWindowTitle("RoadAthena - Login")
        self.setMinimumSize(600, 700)
        self.resize(450, 500)
        
        # Standard window with resize controls
        self.setWindowFlags(Qt.WindowType.Window | 
                        Qt.WindowType.WindowTitleHint |
                        Qt.WindowType.WindowCloseButtonHint |
                        Qt.WindowType.WindowMinMaxButtonsHint)

        self.setFont(QFont("Segoe UI", 10))
        
        # Initialize input field references
        self.username_input = None
        self.password_input = None
        
        self.setup_ui()

    def setup_ui(self):
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(0)

        # Main container
        container = QWidget()
        container.setObjectName("container")
        container.setStyleSheet("""
            #container {
                background: white;
                border-radius: 10px;
                border: 2px solid #e0e0e0;
            }
        """)
        
        # Main layout for container
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # Header section
        header_widget = self.create_header()
        container_layout.addWidget(header_widget)

        # Form section
        form_widget = self.create_form()
        container_layout.addWidget(form_widget, 1)  # Allow form to expand

        # Footer section
        footer_widget = self.create_footer()
        container_layout.addWidget(footer_widget)

        main_layout.addWidget(container)
        self.load_saved_credentials()

        # Connect signals
        if self.username_input:
            self.username_input.returnPressed.connect(self.attempt_login)
        if self.password_input:
            self.password_input.returnPressed.connect(self.attempt_login)
        
        if self.username_input:
            self.username_input.setFocus()

    def create_header(self):
        widget = QWidget()
        widget.setFixedHeight(100)
        widget.setStyleSheet("""
            QWidget {
                background: #2c3e50;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }
        """)
        layout = QVBoxLayout(widget)
        layout.setSpacing(5)
        layout.setContentsMargins(20, 15, 20, 15)

        # Title
        title_label = QLabel("RoadAthena")
        title_label.setStyleSheet("""
            font-size: 24px;
            font-weight: bold;
            color: white;
            padding: 5px;
        """)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle_label = QLabel("Road Data Management System")
        subtitle_label.setStyleSheet("""
            font-size: 12px;
            color: #bdc3c7;
            font-weight: 500;
        """)
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        
        return widget

    def create_form(self):
        form_widget = QWidget()
        form_widget.setStyleSheet("background: white;")
        
        form_layout = QVBoxLayout(form_widget)
        form_layout.setContentsMargins(30, 30, 30, 20)
        form_layout.setSpacing(20)

        # Form title
        title_label = QLabel("Login to Your Account")
        title_label.setStyleSheet("""
            font-size: 18px;
            font-weight: 600;
            color: #2c3e50;
            background: transparent;
        """)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        form_layout.addWidget(title_label)

        # Input fields
        input_layout = QVBoxLayout()
        input_layout.setSpacing(15)

        # Username input
        username_container = QWidget()
        username_layout = QVBoxLayout(username_container)
        username_layout.setContentsMargins(0, 0, 0, 0)
        username_layout.setSpacing(5)
        
        username_label = QLabel("Username")
        username_label.setStyleSheet("""
            color: #5a6c7d;
            font-size: 13px;
            font-weight: 600;
        """)
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter your username")
        self.username_input.setStyleSheet("""
            QLineEdit {
                padding: 12px 15px;
                border: 2px solid #e9ecef;
                border-radius: 8px;
                font-size: 14px;
                background: #ffffff;
                color: #2c3e50;
            }
            QLineEdit:focus {
                border: 2px solid #3498db;
                background: #f8f9fa;
            }
        """)
        
        username_layout.addWidget(username_label)
        username_layout.addWidget(self.username_input)
        input_layout.addWidget(username_container)

        # Password input
        password_container = QWidget()
        password_layout = QVBoxLayout(password_container)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(5)
        
        password_label = QLabel("Password")
        password_label.setStyleSheet("""
            color: #5a6c7d;
            font-size: 13px;
            font-weight: 600;
        """)
        
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter your password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setStyleSheet("""
            QLineEdit {
                padding: 12px 15px;
                border: 2px solid #e9ecef;
                border-radius: 8px;
                font-size: 14px;
                background: #ffffff;
                color: #2c3e50;
            }
            QLineEdit:focus {
                border: 2px solid #3498db;
                background: #f8f9fa;
            }
        """)
        
        password_layout.addWidget(password_label)
        password_layout.addWidget(self.password_input)
        input_layout.addWidget(password_container)

        # Remember me
        self.remember_checkbox = QCheckBox("Remember me")
        self.remember_checkbox.setStyleSheet("""
            QCheckBox {
                color: #5a6c7d;
                font-size: 13px;
                font-weight: 500;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 3px;
                border: 2px solid #bdc3c7;
            }
            QCheckBox::indicator:checked {
                background: #3498db;
                border: 2px solid #3498db;
            }
        """)
        input_layout.addWidget(self.remember_checkbox)

        form_layout.addLayout(input_layout)

        # Status & Progress
        status_layout = QVBoxLayout()
        status_layout.setSpacing(8)

        self.status_label = QLabel()
        self.status_label.setVisible(False)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("""
            padding: 8px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 500;
        """)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background: #ecf0f1;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background: #3498db;
                border-radius: 3px;
            }
        """)
        
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.progress_bar)
        form_layout.addLayout(status_layout)

        # Login Button
        self.login_button = QPushButton("Login")
        self.login_button.setMinimumHeight(45)
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_button.setStyleSheet("""
            QPushButton {
                background: #3498db;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: 600;
                padding: 12px;
            }
            QPushButton:hover {
                background: #2980b9;
            }
            QPushButton:pressed {
                background: #2471a3;
            }
            QPushButton:disabled {
                background: #bdc3c7;
                color: #7f8c8d;
            }
        """)
        self.login_button.clicked.connect(self.attempt_login)
        form_layout.addWidget(self.login_button)

        return form_widget

    def create_footer(self):
        widget = QWidget()
        widget.setFixedHeight(50)
        widget.setStyleSheet("""
            QWidget {
                background: #f8f9fa;
                border-bottom-left-radius: 10px;
                border-bottom-right-radius: 10px;
                border-top: 1px solid #e9ecef;
            }
        """)
        layout = QVBoxLayout(widget)
        layout.setSpacing(2)
        layout.setContentsMargins(20, 8, 20, 8)
        
        # Copyright
        copyright_label = QLabel("© 2025 RoadAthena. All rights reserved.")
        copyright_label.setStyleSheet("""
            color: #7f8c8d;
            font-size: 10px;
        """)
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(copyright_label)
        
        return widget

    # ------------------- LOGIN LOGIC -------------------
    def attempt_login(self):
        if not self.username_input or not self.password_input:
            self.show_status("UI not properly initialized.", True)
            return
            
        username = self.username_input.text().strip()
        password = self.password_input.text()
        
        if not username or not password:
            self.show_status("Please enter both username and password.", True)
            return

        # Disable UI during login
        self.set_ui_enabled(False)
        self.status_label.setVisible(False)
        self.login_button.setText("Authenticating...")
        self.progress_bar.setVisible(True)
        
        # Simulate progress animation
        self.animate_progress()
        
        QTimer.singleShot(500, lambda: self.authenticate_with_api(username, password))

    def set_ui_enabled(self, enabled):
        """Enable or disable UI elements during login process"""
        if self.username_input:
            self.username_input.setEnabled(enabled)
        if self.password_input:
            self.password_input.setEnabled(enabled)
        if hasattr(self, 'remember_checkbox'):
            self.remember_checkbox.setEnabled(enabled)
        if hasattr(self, 'login_button'):
            self.login_button.setEnabled(enabled)

    def animate_progress(self):
        """Animate progress bar during login"""
        self.progress_bar.setRange(0, 0)  # Indeterminate progress

    def authenticate_with_api(self, username, password):
        try:
            auth_url = "https://labelme.roadathena.com/api/login/"
            payload = {"username": username, "password": password}
            headers = {"Content-Type": "application/json", "Accept": "application/json"}

            response = requests.post(auth_url, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                self.auth_token = data.get('session_key', data.get('token', ''))
                self.user_data = data.get('user', {})
                self.dash_url = self.extract_user_url(self.user_data)

                # If we got a dash URL, use it as the API base URL as well
                if self.dash_url:
                    self.selected_api_url = self.dash_url

                self.show_status("Login successful! Redirecting...", False)
                self.save_credentials()

                # Emit success signal with user data
                self.login_successful.emit({
                    'user_data': self.user_data,
                    'auth_token': self.auth_token,
                    'dash_url': self.dash_url,
                    'api_url': self.selected_api_url
                })
                
                QTimer.singleShot(1500, self.accept)
            else:
                error = response.json().get('message', 'Login failed. Please check your credentials.')
                self.show_status(f"Error: {error}", True)
                self.reset_login_button()
                
        except requests.exceptions.Timeout:
            self.show_status("Connection timeout. Please try again.", True)
            self.reset_login_button()
        except requests.exceptions.ConnectionError:
            self.show_status("Connection error. Please check your network.", True)
            self.reset_login_button()
        except Exception as e:
            self.show_status(f"Error: {str(e)}", True)
            self.reset_login_button()


    def extract_user_url(self, user_data):
        """Extract the dashboard/annotator URL from the login response.

        The API can return different fields depending on the deployment:
        - `dashboard_url` (dict or string)
        - `annotator_url` (dict or string)
        """
        for key in ('dashboard_url', 'annotator_url'):
            url_obj = user_data.get(key)
            if isinstance(url_obj, dict):
                url = url_obj.get('url')
                if url:
                    return url
            elif isinstance(url_obj, str):
                return url_obj
        return None

    def load_saved_credentials(self):
        try:
            config_file = Path("user_config.json")
            if config_file.exists():
                with open(config_file, 'r') as f:
                    data = json.load(f)
                    if data.get('remember_me'):
                        if self.username_input:
                            self.username_input.setText(data.get('username', ''))
                        if self.password_input:
                            self.password_input.setText(data.get('password', ''))
                        self.remember_checkbox.setChecked(True)
        except Exception:
            pass

    def save_credentials(self):
        if self.remember_checkbox.isChecked():
            config = {
                'username': self.username_input.text() if self.username_input else '',
                'password': self.password_input.text() if self.password_input else '',
                'remember_me': True,
                'api_url': self.selected_api_url,
                'dash_url': self.dash_url
            }
            with open("user_config.json", 'w') as f:
                json.dump(config, f, indent=4)
        else:
            config_file = Path("user_config.json")
            if config_file.exists():
                config_file.unlink()

    def show_status(self, message, is_error=True):
        self.status_label.setText(message)
        self.status_label.setVisible(True)
        
        if is_error:
            self.status_label.setStyleSheet("""
                color: #e74c3c;
                background: #fadbd8;
                padding: 8px;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 500;
            """)
        else:
            self.status_label.setStyleSheet("""
                color: #27ae60;
                background: #d5f4e6;
                padding: 8px;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 500;
            """)

    def reset_login_button(self):
        self.set_ui_enabled(True)
        self.login_button.setText("Login")
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)  # Reset to determinate progress


# ---------------- S3 UPLOAD THREAD ----------------
class S3UploadThread(QThread):
    """Thread for handling S3 upload operations with enhanced logging"""
    log_signal = pyqtSignal(str, str)
    progress_signal = pyqtSignal(int, int, str)  # current, total, filename
    finished_signal = pyqtSignal(dict)
    
    def __init__(self, main_app, folder_to_upload, s3_client, aws_base_name, 
                 bucket_name, model_type, survey_id_for_s3, process_start_time=None):
        super().__init__()
        self.main_app = main_app
        self.folder_to_upload = Path(folder_to_upload)
        self.s3_client = s3_client
        self.aws_base_name = aws_base_name
        self.bucket_name = bucket_name
        self.model_type = model_type
        self.survey_id_for_s3 = survey_id_for_s3
        self.process_start_time = process_start_time if process_start_time else time.monotonic()
        self.cancelled = False
        self.VIDEO_FILE_FORMATS = VIDEO_FILE_FORMATS
        self.username = getattr(main_app, 'username', 'Unknown')
        
        # Smooth progress tracking
        self.total_bytes = 0
        self.uploaded_bytes = 0
        self.bytes_lock = threading.Lock()
        
    def fetch_existing_files(self, bucket_name, prefix):
        """Fetch all existing file keys and sizes from S3 prefix"""
        existing = {}
        try:
            # Determine prefix
            # Ensure prefix ends with slash if it's a directory
            if not prefix.endswith('/'):
                 prefix += '/'
                 
            self.log_signal.emit(f"Fetching existing S3 files list from {prefix}...", "info")
            paginator = self.s3_client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
            
            count = 0
            for page in page_iterator:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        key = obj['Key']
                        size = obj['Size']
                        existing[key] = size
                        count += 1
            self.log_signal.emit(f"Found {count} existing files on S3.", "info")
        except Exception as e:
            self.log_signal.emit(f"Error fetching existing S3 files: {e}", "warning")
            # Return None to indicate failure, so we fall back to head_object
            return None
        return existing

    def run(self):
        try:
            result = self.uploadFileToS3()
            self.finished_signal.emit(result)
        except Exception as e:
            self.log_signal.emit(f"Unexpected error in S3 upload: {str(e)}", "error")
            self.finished_signal.emit({
                "success_count": 0,
                "failed_count": 0,
                "success_files": [],
                "failed_files": [],
                "error": str(e)
            })
    
    def cancel(self):
        self.cancelled = True
    
    def upload_file_to_s3(self, file_path: Path, s3_client, bucket_name: str, s3_key: str, 
                           max_retries=5, existing_files_map=None) -> bool:
        """
        Uploads a single file to S3 with enhanced reliability, progress tracking, and error handling.
        """
        if self.cancelled:
            self.log_signal.emit(f"Upload cancelled for {file_path.name} before starting.", "warning")
            return False
            
        try:
            file_size = file_path.stat().st_size
            self.log_signal.emit(f"Preparing to upload: {file_path.name} ({file_size / (1024*1024):.2f} MB) to s3://{bucket_name}/{s3_key}", "info")

            # Optimized config for balance between speed and low memory usage
            config = TransferConfig(
                multipart_threshold=16 * 1024 * 1024,
                max_concurrency=2,  # Reduced concurrency for reliability
                multipart_chunksize=16 * 1024 * 1024,
                use_threads=True,
                max_io_queue=20,    # SIGNIFICANTLY REDUCED: Prevents extreme RAM usage (prevents buffering too many chunks)
                io_chunksize=1024 * 1024,
                num_download_attempts=3,
                max_bandwidth=None
            )

            # Enhanced duplicate check with metadata comparison
            check_s3_head = True
            
            if existing_files_map is not None:
                if s3_key in existing_files_map:
                    if existing_files_map[s3_key] == file_size:
                        self.log_signal.emit(f"File '{file_path.name}' already exists on S3 with same size. Skipping.", "info")
                        return True
                    check_s3_head = False # Key exists but size differs, proceed to upload (overwrite) or user might want to know? 
                                          # Usually overwritten. We skip head_object as we know state.
                else:
                    check_s3_head = False # Key not in map, so it definitely doesn't exist (assuming map is fresh)

            if check_s3_head:
                try:
                    head_response = s3_client.head_object(Bucket=bucket_name, Key=s3_key)
                    existing_size = head_response.get('ContentLength', 0)
                    
                    if existing_size == file_size:
                        self.log_signal.emit(f"File '{file_path.name}' already exists on S3 with same size. Skipping.", "info")
                        return True
                        
                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                    if error_code != '404':
                        self.log_signal.emit(f"Warning: Error checking S3 object '{s3_key}': {error_code} - {e}", "warning")
                except Exception as e:
                    self.log_signal.emit(f"Warning: Unexpected error checking S3 object: {e}", "warning")

            # Progress tracking variables
            progress_lock = threading.Lock()
            uploaded_bytes = 0
            start_time_upload = time.monotonic()
            last_percentage_update = start_time_upload
            last_percentage = 0
            
            def progress_callback(bytes_transferred):
                nonlocal uploaded_bytes, last_percentage_update, last_percentage
                
                if self.cancelled:
                    raise InterruptedError("S3 upload cancelled by user.")

                with progress_lock:
                    uploaded_bytes += bytes_transferred
                    
                    # Update global bytes IMMEDIATELY to avoid losing progress between emissions
                    with self.bytes_lock:
                        self.uploaded_bytes += bytes_transferred
                        global_uploaded = self.uploaded_bytes
                        global_total = self.total_bytes

                    # Calculate percentage for THIS file (for emission throttle decision)
                    current_percentage = (uploaded_bytes / file_size) * 100 if file_size > 0 else 0
                    
                    # Emit progress Every second or when percentage changes significantly
                    current_time = time.monotonic()
                    if (current_time - last_percentage_update >= 0.5 or  # Every 0.5s for smoother feel
                        abs(current_percentage - last_percentage) >= 2.0 or  # Or 2% change
                        uploaded_bytes == file_size):  # Or when complete
                        
                        # Update throttle markers
                        last_percentage_update = current_time
                        last_percentage = current_percentage

                        # Emit global progress signal
                        if global_total > 0:
                            self.progress_signal.emit(global_uploaded, global_total, file_path.name)
                        
                        elapsed_since_start = current_time - self.process_start_time
                        elapsed_upload = current_time - start_time_upload
                        
                        if elapsed_upload > 0:
                            file_speed_mbps = (uploaded_bytes / (1024*1024)) / elapsed_upload
                        else:
                            file_speed_mbps = 0
                            
                        if elapsed_since_start > 0:
                            overall_speed_mbps = (global_uploaded / (1024*1024)) / elapsed_since_start
                        else:
                            overall_speed_mbps = 0
                        
                        percent = min((uploaded_bytes / file_size) * 100, 100) if file_size > 0 else 0
                        
                        progress_bar_length = 25
                        filled_length = int(progress_bar_length * uploaded_bytes // file_size) if file_size > 0 else 0
                        bar = '█' * filled_length + '▒' * (progress_bar_length - filled_length)
                        
                        if overall_speed_mbps > 0 and global_uploaded < global_total:
                            remaining_mb = (global_total - global_uploaded) / (1024*1024)
                            eta_seconds = remaining_mb / overall_speed_mbps
                            eta_str = f" | Total ETA: {int(eta_seconds//60):02d}:{int(eta_seconds%60):02d}"
                        else:
                            eta_str = ""
                        
                        progress_msg = (f"[{bar}] {percent:.1f}% "
                                    f"({uploaded_bytes/(1024*1024):.1f}/{file_size/(1024*1024):.1f} MB) "
                                    f"| {file_speed_mbps:.1f} MB/s{eta_str} | {file_path.name}")
                        
                        self.log_signal.emit(progress_msg, "info")
                        
                        last_percentage_update = current_time
                        last_percentage = current_percentage

            # Enhanced retry logic with exponential backoff
            @backoff.on_exception(
                backoff.expo,
                (ClientError, BotoCoreError, requests.exceptions.RequestException, 
                 ConnectionError, TimeoutError, OSError, IOError),
                max_tries=max_retries,
                max_time=1800,
                base=2,
                factor=1.5,
                jitter=backoff.full_jitter,
                on_backoff=lambda details: self.log_signal.emit(
                    f"Retry {details['tries']}/{max_retries} for {file_path.name} "
                    f"after {details['wait']:.1f}s (Exception: {details['exception'].__class__.__name__})", 
                    "warning"
                ),
                on_giveup=lambda details: self.log_signal.emit(
                    f"Giving up S3 upload for {file_path.name} after {details['tries']} attempts. "
                    f"Final error: {details['exception']}", "error"
                )
            )
            def upload_with_retries():
                nonlocal uploaded_bytes, start_time_upload, last_percentage_update, last_percentage
                
                with progress_lock:
                    uploaded_bytes = 0
                    start_time_upload = time.monotonic()
                    last_percentage_update = start_time_upload
                    last_percentage = 0
                
                if not file_path.exists():
                    raise FileNotFoundError(f"Source file no longer exists: {file_path}")
                
                if file_path.stat().st_size != file_size:
                    raise ValueError(f"File size changed during upload: {file_path}")
                
                s3_client.upload_file(
                    str(file_path), 
                    bucket_name, 
                    s3_key,
                    Config=config,
                    Callback=progress_callback
                )

            upload_with_retries()
            
            # Final verification
            try:
                head_response = s3_client.head_object(Bucket=bucket_name, Key=s3_key)
                uploaded_size = head_response.get('ContentLength', 0)
                if uploaded_size != file_size:
                    raise ValueError(f"Upload verification failed: expected {file_size}, got {uploaded_size}")
            except Exception as verify_error:
                self.log_signal.emit(f"Upload verification warning for {file_path.name}: {verify_error}", "warning")
            
            total_time_upload = time.monotonic() - start_time_upload
            avg_speed_mbps = (file_size / (1024*1024)) / max(total_time_upload, 0.1)
            
            self.log_signal.emit(
                f"Successfully uploaded: {file_path.name} in {total_time_upload:.1f}s "
                f"(Avg: {avg_speed_mbps:.2f} MB/s)", "success"
            )
            return True

        except InterruptedError:
            self.log_signal.emit(f"S3 upload cancelled: {file_path.name}", "warning")
            return False
        except Exception as e:
            error_msg = f"Failed to upload {file_path.name}: {type(e).__name__}: {e}"
            self.log_signal.emit(error_msg, "error")
            return False

    def uploadFileToS3(self):
        """Enhanced recursive S3 upload with improved reliability, progress tracking, and error handling."""
        try:
            if not self.folder_to_upload.exists():
                raise ValueError(f"Source folder does not exist: {self.folder_to_upload}")

            self.log_signal.emit(f"Starting S3 upload from: {self.folder_to_upload}", "info")

            # Enhanced tracking system
            today_str = datetime.now().strftime('%Y%m%d')
            log_file_path = "N/A" # Placeholder as real log file path not yet chosen 
            uploaded_info_dir = Path.cwd() / "upload_data" / f"upload_info_{today_str}"
            uploaded_info_dir.mkdir(parents=True, exist_ok=True)
            tracking_file_path = uploaded_info_dir / f"upload_tracking_{self.survey_id_for_s3}.json"
            backup_tracking_path = uploaded_info_dir / f"upload_tracking_{self.survey_id_for_s3}_backup.json"

            upload_tracking = {}
            
            # Load existing tracking with backup recovery
            for tracking_path in [tracking_file_path, backup_tracking_path]:
                if tracking_path.exists():
                    try:
                        with open(tracking_path, "r", encoding="utf-8") as f:
                            upload_tracking = json.load(f)
                        self.log_signal.emit(f"Loaded upload tracking from {tracking_path.name}", "info")
                        break
                    except (json.JSONDecodeError, IOError) as e:
                        self.log_signal.emit(f"Corrupt tracking file {tracking_path.name}: {e}", "warning")

            def save_tracking():
                """Save tracking with atomic write and backup"""
                tracking_data = {
                    "last_updated": datetime.now().isoformat(),
                    "survey_id": self.survey_id_for_s3,
                    "username": self.username,
                    "files": upload_tracking
                }
                
                temp_path = tracking_file_path.with_suffix('.tmp')
                try:
                    with open(temp_path, "w", encoding="utf-8") as f:
                        json.dump(tracking_data, f, indent=2, ensure_ascii=False)
                    
                    if tracking_file_path.exists():
                        shutil.copy2(tracking_file_path, backup_tracking_path)
                    
                    if os.name == 'nt':
                        if tracking_file_path.exists():
                            os.remove(tracking_file_path)
                    shutil.move(str(temp_path), str(tracking_file_path))
                    
                except Exception as save_error:
                    self.log_signal.emit(f"Failed to save tracking: {save_error}", "warning")

            # Enhanced archive directory
            uploaded_files_archive_dir = Path.cwd() / "uploaded_files_archive" / f"survey_{self.survey_id_for_s3}" / today_str
            uploaded_files_archive_dir.mkdir(parents=True, exist_ok=True)

            # Track which roads actually received videos
            roads_with_videos = set()

            # Comprehensive file discovery
            files_to_upload = []
            
            self.log_signal.emit("Scanning for video files...", "info")

            short_api = self.aws_base_name
            self.log_signal.emit(f"Selected API identifier: {short_api}", "info")
            
            # Optimization: Pre-fetch existing files on S3 to avoid N head_object calls
            s3_prefix = f"input/videos/{self.model_type}/{short_api}/survey_{self.survey_id_for_s3}/"
            existing_files_map = self.fetch_existing_files(self.bucket_name, s3_prefix)
            
            try:
                for root, dirs, files in os.walk(self.folder_to_upload):
                    # Skip hidden directories and common system directories
                    dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in ['__pycache__', 'thumbs.db']]
                    
                    if self.cancelled:
                        break
                        
                    for file_name in files:
                        if self.cancelled:
                            break
                            
                        if any(file_name.lower().endswith(ext.lower()) for ext in self.VIDEO_FILE_FORMATS):
                            try:
                                local_path = Path(root) / file_name
                                
                                # Enhanced file validation
                                if not local_path.exists():
                                    continue
                                    
                                file_stat = local_path.stat()
                                if file_stat.st_size == 0:
                                    self.log_signal.emit(f"Skipping empty file: {local_path}", "warning")
                                    continue
                                    
                                relative_path = local_path.relative_to(self.folder_to_upload).as_posix()
                                s3_key = f"input/videos/{self.model_type}/{short_api}/survey_{self.survey_id_for_s3}/{relative_path}"
                                
                                # Enhanced file hash for better duplicate detection
                                file_hash = f"{file_stat.st_size}_{int(file_stat.st_mtime)}_{file_stat.st_ino if hasattr(file_stat, 'st_ino') else 0}"
                                
                                # Check if already uploaded successfully
                                file_key = str(local_path)
                                if (file_key in upload_tracking and 
                                    upload_tracking[file_key].get("hash") == file_hash and
                                    upload_tracking[file_key].get("status") == "success"):
                                    
                                    self.log_signal.emit(f"Skipping already uploaded: {local_path.name}", "info")
                                    continue

                                files_to_upload.append((local_path, s3_key, file_hash))
                                
                            except (OSError, PermissionError) as file_error:
                                self.log_signal.emit(f"Cannot access file {file_name}: {file_error}", "warning")
                                
            except Exception as scan_error:
                self.log_signal.emit(f"Error scanning directory: {scan_error}", "error")
                return {
                    "success_count": 0, 
                    "failed_count": 0, 
                    "success_files": [], 
                    "failed_files": [], 
                    "roads_with_videos": []  # Add empty list for error case
                }

            if not files_to_upload:
                message = f"No new video files found in {self.folder_to_upload}"
                self.log_signal.emit(message, "warning")
                return {
                    "success_count": 0, 
                    "failed_count": 0, 
                    "success_files": [], 
                    "failed_files": [], 
                    "roads_with_videos": []  # Add empty list for no files case
                }

            self.log_signal.emit(f"Found {len(files_to_upload)} new video file(s) to upload", "info")
            write_to_file_log(f"Starting upload of {len(files_to_upload)} files")

            # Upload tracking
            success_list = []
            fail_list = []
            self.total_bytes = sum(path.stat().st_size for path, _, _ in files_to_upload)
            self.uploaded_bytes = 0
            
            upload_stats = {
                "start_time": time.monotonic(),
                "total_files": len(files_to_upload),
                "completed_files": 0,
                "total_bytes": self.total_bytes,
                "uploaded_bytes": 0
            }

            def upload_job(local_path: Path, s3_key: str, file_hash: str):
                """Enhanced upload job with comprehensive error handling"""
                print(f"DEBUG: upload_job started for {local_path}")
                file_key = str(local_path)
                
                try:
                    if self.cancelled:
                        self.log_signal.emit(f"Upload cancelled: {local_path.name}", "warning")
                        return False

                    # Pre-upload validation
                    if not local_path.exists():
                        raise FileNotFoundError(f"File disappeared: {local_path}")
                        
                    current_size = local_path.stat().st_size
                    if current_size == 0:
                        raise ValueError(f"File is empty: {local_path}")

                    # Attempt upload
                    upload_start = time.monotonic()
                    result = self.upload_file_to_s3(local_path, self.s3_client, self.bucket_name, s3_key, existing_files_map=existing_files_map)
                    upload_duration = time.monotonic() - upload_start

                    if result and not self.cancelled:
                        # Update tracking
                        upload_tracking[file_key] = {
                            "s3_path": s3_key,
                            "hash": file_hash,
                            "timestamp": datetime.now().isoformat(),
                            "status": "success",
                            "upload_duration": upload_duration,
                            "file_size": current_size,
                            "username": self.username
                        }
                        save_tracking()

                        success_list.append(file_key)
                        upload_stats["completed_files"] += 1
                        upload_stats["uploaded_bytes"] += current_size
                        
                        # write_to_file_log(f"SUCCESS: {local_path} -> {s3_key}")

                        # Track road ID from the file path
                        try:
                            # Extract road ID from the path structure
                            # Path format: .../road_123/filename.mp4
                            path_parts = local_path.parts
                            for i, part in enumerate(path_parts):
                                if part.startswith('road_'):
                                    road_id = int(part.replace('road_', ''))
                                    roads_with_videos.add(road_id)
                                    self.log_signal.emit(f"📦 Added video from road_{road_id} to upload tracking", "info")
                                    break
                        except Exception as e:
                            self.log_signal.emit(f"Could not extract road ID from {local_path}: {e}", "warning")

                        # Safe file archiving
                        try:
                            archive_path = uploaded_files_archive_dir / local_path.name
                            counter = 1
                            while archive_path.exists():
                                stem = local_path.stem
                                suffix = local_path.suffix
                                archive_path = uploaded_files_archive_dir / f"{stem}_{counter}{suffix}"
                                counter += 1

                            shutil.copy2(local_path, archive_path)
                            
                            # Safe file removal with verification
                            if archive_path.exists() and archive_path.stat().st_size == current_size:
                                os.remove(local_path)
                                self.log_signal.emit(f"Archived and removed: {local_path.name}", "info")
                            else:
                                self.log_signal.emit(f"Archive verification failed for: {local_path.name}", "warning")
                                
                        except Exception as archive_error:
                            error_msg = f"Archive failed for {local_path.name}: {archive_error}"
                            self.log_signal.emit(f"{error_msg}", "warning")
                            write_to_file_log(f"ARCHIVE_ERROR: {error_msg}", "WARNING")

                    return result
                    
                except Exception as job_error:
                    if not self.cancelled:
                        upload_tracking[file_key] = {
                            "s3_path": s3_key,
                            "hash": file_hash,
                            "timestamp": datetime.now().isoformat(),
                            "status": "failed",
                            "error": str(job_error),
                            "error_type": type(job_error).__name__,
                            "username": self.username
                        }
                        save_tracking()

                        fail_list.append(file_key)
                        error_msg = f"FAILED: {local_path} - {type(job_error).__name__}: {job_error}"
                        self.log_signal.emit(f"{error_msg}", "error")
                        # write_to_file_log(error_msg, "ERROR")
                        
                    return False

            # Enhanced threaded upload with progress monitoring
            num_workers = min(4, len(files_to_upload), 6)  # Max 6 workers
            
            self.log_signal.emit(f"Using {num_workers} upload workers", "info")
            write_to_file_log(f"Using {num_workers} upload workers")

            progress_start_time = time.monotonic()
            last_progress_report = progress_start_time

            with ThreadPoolExecutor(max_workers=num_workers, thread_name_prefix="S3Upload") as executor:
                # Submit all jobs
                futures = {}
                for local_path, s3_key, file_hash in files_to_upload:
                    if self.cancelled:
                        break
                    future = executor.submit(upload_job, local_path, s3_key, file_hash)
                    futures[future] = local_path

                # Monitor progress
                for future in as_completed(futures):
                    current_time = time.monotonic()
                    local_path = futures[future]
                    
                    if self.cancelled:
                        self.log_signal.emit("Cancelling remaining uploads...", "warning")
                        break

                    # self.progress_signal.emit(completed, total, local_path.name)

                    # Periodic progress report
                    if current_time - last_progress_report >= 10:  # Every 10 seconds
                        completed = upload_stats["completed_files"] + len(fail_list)
                        total = upload_stats["total_files"]
                        
                        global_uploaded = self.uploaded_bytes
                        global_total = self.total_bytes
                        elapsed_since_start = current_time - self.process_start_time
                        
                        if global_uploaded > 0 and elapsed_since_start > 0:
                            overall_speed_mbps = (global_uploaded / (1024*1024)) / elapsed_since_start
                            remaining_mb = (global_total - global_uploaded) / (1024*1024)
                            remaining_time = remaining_mb / overall_speed_mbps if overall_speed_mbps > 0 else 0
                            
                            progress_msg = (f"Overall Progress: {completed}/{total} files "
                                        f"({global_uploaded/(1024*1024):.1f}/{global_total/(1024*1024):.1f} MB) | "
                                        f"Total ETA: {int(remaining_time//60):02d}:{int(remaining_time%60):02d}")
                            
                            self.log_signal.emit(progress_msg, "info")
                            write_to_file_log(progress_msg)
                        
                        last_progress_report = current_time

            # Final summary with actual elapsed time
            total_time_upload = time.monotonic() - progress_start_time
            total_time_process = time.monotonic() - self.process_start_time
            success_count = len(success_list)
            failed_count = len(fail_list)
            
            # Format total process time in readable format
            hours = int(total_time_process // 3600)
            minutes = int((total_time_process % 3600) // 60)
            seconds = int(total_time_process % 60)
            
            process_time_str = f"{hours}h {minutes}m {seconds}s" if hours > 0 else f"{minutes}m {seconds}s"
            
            self.log_signal.emit(
                f"S3 Upload Process Summary: {success_count} success, {failed_count} failed in {total_time_upload:.1f}s. "
                f"Total Process Time (Sorting + Upload): {process_time_str}", "info"
            )
            
            if hours > 0:
                time_display = f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                time_display = f"{minutes}m {seconds}s"
            else:
                time_display = f"{seconds}s"
            
            # Log road information
            sorted_road_ids = sorted(list(roads_with_videos))
            if sorted_road_ids:
                self.log_signal.emit(f"🛣️ Videos uploaded from {len(sorted_road_ids)} roads: {sorted_road_ids}", "success")
                write_to_file_log(f"Roads with uploaded videos: {sorted_road_ids}")
            else:
                self.log_signal.emit("⚠️ No road IDs detected in uploaded files", "warning")
                write_to_file_log("No road IDs detected in uploaded files", "WARNING")
            
            if upload_stats["uploaded_bytes"] > 0:
                avg_speed = (upload_stats["uploaded_bytes"] / (1024*1024)) / max(total_time_upload, 1)
                speed_info = f" | Avg Speed: {avg_speed:.2f} MB/s"
            else:
                speed_info = ""

            summary = (f"✅ Upload Complete: {success_count} succeeded, {failed_count} failed "
                    f"⏱️ Total Time: {time_display}{speed_info}")
            
            result_level = "success" if failed_count == 0 else "warning" if success_count > 0 else "error"
            self.log_signal.emit(summary, result_level)
            write_to_file_log(summary, "SUMMARY")

            # Generate HTML log with time settings
            html_log_data = {
                "username": self.username,
                "survey_id": self.survey_id_for_s3,
                "survey_name": f"Survey {self.survey_id_for_s3}",
                "start_time": datetime.now().isoformat(),
                "system_info": get_system_info(),
                "time_settings": getattr(self.main_app, 'current_time_settings', {
                    'time_option': 'Not specified',
                    'start_buffer': 'Not specified', 
                    'end_buffer': 'Not specified'
                }),
                "model_type": self.model_type,
                "road_ids": sorted_road_ids,
                "entries": self._prepare_html_log_entries(success_count, failed_count, total_time_upload, upload_stats, sorted_road_ids)
            }
            
            html_log_path = HTMLLogGenerator.create_html_log(html_log_data)
            self.log_signal.emit(f"HTML log generated: {html_log_path}", "info")

            # Upload HTML log to server
            session_data = {
                'session_id': f"s3_upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                'success': failed_count == 0,
                'roads_processed': len(sorted_road_ids),
                'files_uploaded': success_count,
                'files_failed': failed_count,
                'processing_type': 's3_upload',
                'total_bytes': upload_stats["uploaded_bytes"],
                'upload_duration': total_time_upload
            }
            
            # Upload HTML log to Django server
            if hasattr(self.main_app, 'upload_html_log_to_server'):
                upload_success = self.main_app.upload_html_log_to_server(html_log_path, session_data)
                if upload_success:
                    self.log_signal.emit("✅ S3 upload HTML log uploaded to server successfully", "success")
                else:
                    self.log_signal.emit("⚠️ S3 upload HTML log saved locally but failed to upload to server", "warning")
            else:
                self.log_signal.emit("ℹ️ S3 upload HTML log saved locally (upload method not available)", "info")

            return {
                "success_count": success_count,
                "failed_count": failed_count,
                "success_files": success_list,
                "failed_files": fail_list,
                "log_file": str(log_file_path),
                "html_log_file": str(html_log_path),
                "total_time": total_time_upload,
                "total_bytes_uploaded": upload_stats["uploaded_bytes"],
                "tracking_file": str(tracking_file_path),
                "roads_with_videos": sorted_road_ids  # Add road IDs to return data
            }

        except Exception as main_error:
            error_msg = f"Critical error in uploadFileToS3: {type(main_error).__name__}: {main_error}"
            self.log_signal.emit(error_msg, "error")
            
            try:
                write_to_file_log(error_msg, "CRITICAL")
            except:
                pass
                
            return {
                "success_count": 0,
                "failed_count": 0,
                "success_files": [],
                "failed_files": [],
                "log_file": str(log_file_path) if 'log_file_path' in locals() else "N/A",
                "error": str(main_error),
                "roads_with_videos": []  # Add empty list for error case
            }
   
   
    def _prepare_html_log_entries(self, success_count, failed_count, total_time, upload_stats, road_ids):
        """Prepare log entries for HTML log generation with road IDs"""
        # Get time settings from main app if available
        time_settings = {}
        if hasattr(self.main_app, 'current_time_settings'):
            time_settings = self.main_app.current_time_settings
        else:
            # Fallback to default values
            time_settings = {
                "time_option": "Not specified",
                "start_buffer": "Not specified", 
                "end_buffer": "Not specified"
            }
        
        model_type = self.model_type
        
        entries = [
            {
                "timestamp": datetime.now().isoformat(),
                "level": "info",
                "message": f"S3 Upload Session Started - User: {self.username}"
            },
            {
                "timestamp": datetime.now().isoformat(),
                "level": "info",
                "message": f"Survey ID: {self.survey_id_for_s3}"
            },
            {
                "timestamp": datetime.now().isoformat(),
                "level": "info",
                "message": f"Model Type: {model_type}"
            },
            {
                "timestamp": datetime.now().isoformat(),
                "level": "info",
                "message": f"Time Settings: {time_settings.get('time_option', 'Not specified')}"
            },
            {
                "timestamp": datetime.now().isoformat(),
                "level": "info",
                "message": f"Start Buffer: {time_settings.get('start_buffer', 'Not specified')}s, End Buffer: {time_settings.get('end_buffer', 'Not specified')}s"
            },
            {
                "timestamp": datetime.now().isoformat(),
                "level": "info",
                "message": f"Total files to upload: {upload_stats['total_files']}"
            },
            {
                "timestamp": datetime.now().isoformat(),
                "level": "success" if success_count > 0 else "warning",
                "message": f"Successfully uploaded: {success_count} files"
            }
        ]
        
        # Add road IDs information
        if road_ids:
            entries.append({
                "timestamp": datetime.now().isoformat(),
                "level": "info",
                "message": f"Roads with uploaded videos: {len(road_ids)} roads - IDs: {', '.join(map(str, road_ids))}"
            })
            entries.append({
                "timestamp": datetime.now().isoformat(),
                "level": "info",
                "message": f"Videos moved to uploaded_files_archive for roads: {sorted(road_ids)}"
            })
        else:
            entries.append({
                "timestamp": datetime.now().isoformat(),
                "level": "warning",
                "message": "No road IDs detected in uploaded files"
            })
        
        if failed_count > 0:
            entries.append({
                "timestamp": datetime.now().isoformat(),
                "level": "error",
                "message": f"Failed to upload: {failed_count} files"
            })
        
        entries.append({
            "timestamp": datetime.now().isoformat(),
            "level": "info",
            "message": f"Total upload time: {total_time:.1f}s"
        })
        
        if upload_stats["uploaded_bytes"] > 0:
            avg_speed = (upload_stats["uploaded_bytes"] / (1024*1024)) / max(total_time, 1)
            entries.append({
                "timestamp": datetime.now().isoformat(),
                "level": "info",
                "message": f"Average upload speed: {avg_speed:.2f} MB/s"
            })
        
        entries.append({
            "timestamp": datetime.now().isoformat(),
            "level": "success" if failed_count == 0 else "warning",
            "message": "S3 Upload Session Completed"
        })
        
        return entries


# ---------------- PROCESSING THREAD ----------------
class ProcessingThread(QThread):
    """Thread for handling the main processing tasks"""
    log_signal = pyqtSignal(str, str)
    progress_signal = pyqtSignal(int, int, str)  # current, total, filename
    finished_signal = pyqtSignal(bool, str)
    status_signal = pyqtSignal(str)
    
    def __init__(self, main_app, survey_id, source_folder, api_url, model_type, 
             time_setting, start_buffer, end_buffer, upload_to_s3, download_gpx, concatenate_videos=False):
        super().__init__()
        self.main_app = main_app
        self.survey_id = survey_id
        self.source_folder = source_folder
        self.api_url = api_url
        self.model_type = model_type
        self.time_setting = time_setting
        self.start_buffer = start_buffer
        self.end_buffer = end_buffer
        self.upload_to_s3 = upload_to_s3
        self.download_gpx = download_gpx
        self.concatenate_videos = concatenate_videos  # Add this
        self.cancelled = False
        self.VIDEO_FILE_FORMATS = VIDEO_FILE_FORMATS
        self.session_log_file = None
        self.html_log_entries = []
    def run(self):
        try:
            # Initialize enhanced logging
            # username = self.main_app.username if hasattr(self.main_app, 'username') else "Unknown"
            # self.session_log_file = create_session_log_file(username, self.survey_id)
            
            # Log session start with system info
            self.enhanced_log_message(
                "Starting processing session", 
                "info",
                {
                    "survey_id": self.survey_id,
                    "source_folder": self.source_folder,
                    "api_url": self.api_url,
                    "model_type": self.model_type,
                    "system_info": get_system_info()
                }
            )
            
            self.process_data()
        except Exception as e:
            self.enhanced_log_message(f"Unexpected error: {str(e)}", "error")
            self.finished_signal.emit(False, str(e))
    
    def cancel(self):
        self.cancelled = True
    
    def enhanced_log_message(self, message, level="info", extra_data=None):
        """Enhanced logging with system and user context"""
        timestamp = datetime.now().isoformat()
        
        # Add to HTML log entries
        self.html_log_entries.append({
            "timestamp": timestamp,
            "level": level,
            "message": message
        })
        
        # Emit to UI
        self.log_signal.emit(message, level)
    
    def process_data(self):
        """Main processing logic"""
        base_api_name = self.api_url.split("//")[1].split(".")[0]
        base_processing_dir = Path.cwd() / "roadathena_processed_data"
        base_processing_dir.mkdir(parents=True, exist_ok=True)
        local_survey_dest_folder = base_processing_dir / f"survey_{self.survey_id}"

        try:
            # Record overall start time for the entire process
            self.overall_process_start_time = time.monotonic()
            
            # Get survey name for logging - use just the survey ID since we don't have the name
            self.enhanced_log_message(f"📋 Processing Survey ID: {self.survey_id}", "info")
            self.progress_signal.emit(0, 100, "Starting processing...")
            
            success_step1 = self.create_folder_structure_and_extract_times(
                self.survey_id, self.api_url, self.time_setting, local_survey_dest_folder
            )
            
            if not success_step1 or self.cancelled:
                if self.cancelled:
                    self.enhanced_log_message("Process cancelled during folder structure creation.", "warning")
                else:
                    self.enhanced_log_message("Failed to create folder structure or extract GPX times. Aborting.", "error")
                self.generate_final_html_log(False)
                self.finished_signal.emit(False, "Processing failed at step 1")
                return
            
            gc.collect() # Helper to free memory after GPX/Folder processing
            
            self.enhanced_log_message("Step 2: Organizing local video files...", "info")
            self.progress_signal.emit(10, 100, "Organizing local video files...")
            success_step2 = self.organize_videos(Path(self.source_folder), local_survey_dest_folder)
            if not success_step2 or self.cancelled:
                if self.cancelled:
                    self.enhanced_log_message("Process cancelled during video organization.", "warning")
                else:
                    self.enhanced_log_message("Failed to organize videos. Aborting S3 upload if planned.", "error")
                self.generate_final_html_log(False)
                self.finished_signal.emit(False, "Processing failed at step 2")
                return
            
            gc.collect() # Helper to free memory after Video organization
            
            if self.upload_to_s3:
                if self.cancelled:
                    self.enhanced_log_message("Process cancelled before S3 upload.", "warning")
                    self.generate_final_html_log(False)
                    self.finished_signal.emit(False, "Processing cancelled")
                    return
                    
                if not self.main_app.s3_client:
                    self.enhanced_log_message("S3 client not initialized. Skipping S3 upload.", "error")
                else:
                    self.enhanced_log_message("Step 3: Uploading files to S3...", "info")
                    self.progress_signal.emit(0, 100, "Initializing S3 upload...")
                    # Start S3 upload thread
                    self.s3_upload_thread = S3UploadThread(
                        self.main_app, local_survey_dest_folder, self.main_app.s3_client,
                        base_api_name, self.main_app.AWS_STORAGE_BUCKET_NAME,
                        self.model_type, self.survey_id, self.overall_process_start_time
                    )
                    self.s3_upload_thread.log_signal.connect(self.enhanced_log_message)
                    self.s3_upload_thread.progress_signal.connect(self.progress_signal.emit)
                    self.s3_upload_thread.finished_signal.connect(self.s3_upload_finished)
                    self.s3_upload_thread.start()
                    return  # Wait for S3 upload to finish
            
            self.enhanced_log_message("Session completed successfully", "info", {"action": "logout"})
            self.generate_final_html_log(True)
            # FIXED: Use only survey_id since survey_name is not available in this context
            self.finished_signal.emit(True, f"Processing completed for Survey ID: {self.survey_id}!")
            
        except Exception as e:
            self.enhanced_log_message(f"Processing failed: {str(e)}", "error")
            self.generate_final_html_log(False)
            self.finished_signal.emit(False, str(e))

    def generate_final_html_log(self, success):
        """Generate final HTML log for the processing session"""
        username = self.main_app.username if hasattr(self.main_app, 'username') else "Unknown"
        
        # Use roads_with_videos if available, otherwise fall back to folder scanning
        if hasattr(self, 'roads_with_videos'):
            road_ids = self.roads_with_videos
        else:
            # Fallback: scan folders for roads that have videos
            road_ids = []
            try:
                base_processing_dir = Path.cwd() / "roadathena_processed_data"
                local_survey_dest_folder = base_processing_dir / f"survey_{self.survey_id}"
                
                if local_survey_dest_folder.exists():
                    for item in local_survey_dest_folder.iterdir():
                        if item.is_dir() and item.name.startswith("road_"):
                            # Check if this road folder has any video files
                            video_files = list(item.glob("*"))
                            video_files = [f for f in video_files if f.suffix.lower() in self.VIDEO_FILE_FORMATS]
                            if video_files:  # Only include roads that have videos
                                try:
                                    road_id = int(item.name.replace("road_", ""))
                                    road_ids.append(road_id)
                                except ValueError:
                                    pass
            except Exception as e:
                self.enhanced_log_message(f"Error extracting road IDs: {e}", "warning")
        
        # Get time settings from main app if available
        time_settings = {}
        if hasattr(self.main_app, 'current_time_settings'):
            time_settings = self.main_app.current_time_settings
        else:
            # Fallback to default values
            time_settings = {
                "time_option": "Not specified",
                "start_buffer": "Not specified", 
                "end_buffer": "Not specified"
            }
        
        log_data = {
            "username": username,
            "survey_id": self.survey_id,
            "survey_name": f"Survey {self.survey_id}",
            "start_time": datetime.now().isoformat(),
            "system_info": get_system_info(),
            "time_settings": time_settings,
            "model_type": self.model_type,
            "concatenation_enabled": self.concatenate_videos,
            "road_ids": road_ids,
            "entries": self.html_log_entries
        }
        
        html_log_path = HTMLLogGenerator.create_html_log(log_data)
        self.enhanced_log_message(f"Session HTML log generated: {html_log_path}", "info")




    def s3_upload_finished(self, result):
        """Handle S3 upload completion"""
        success_count = result.get("success_count", 0)
        failed_count = result.get("failed_count", 0)
        
        if success_count > 0 or failed_count > 0:
            gc.collect() # Helper to free memory after S3 upload completion
        
        html_log_path = result.get("html_log_file", "")
        
        if html_log_path:
            self.enhanced_log_message(f"S3 Upload HTML log: {html_log_path}", "info")
        
        if success_count > 0 and failed_count == 0:
            self.enhanced_log_message(f"✅ S3 upload completed successfully! {success_count} files uploaded.", "success")
            self.enhanced_log_message("🏁 Session completed successfully", "info", {"action": "logout"})
            self.generate_final_html_log(True)
            self.finished_signal.emit(True, f"Processing completed successfully! {success_count} files uploaded to S3.")
        elif success_count > 0:
            self.enhanced_log_message(f"⚠️ S3 upload partially completed. {success_count} succeeded, {failed_count} failed.", "warning")
            self.enhanced_log_message("🏁 Session completed with warnings", "info", {"action": "logout"})
            self.generate_final_html_log(True)
            self.finished_signal.emit(True, f"Processing completed with {success_count} S3 uploads successful and {failed_count} failed.")
        else:
            self.enhanced_log_message("❌ S3 upload failed completely.", "error")
            self.generate_final_html_log(False)
            self.finished_signal.emit(False, "S3 upload failed completely.")
            self.finished_signal.emit(False, "S3 upload failed completely.")

    
    def create_folder_structure_and_extract_times(self, survey_id, base_api_url, gpx_time_modify_setting, local_survey_dest_folder):
        """Implementation from Tkinter with road filtering support"""
        try:
            api_call_url = f"{base_api_url.rstrip('/')}/api/surveys/{survey_id}"
            self.enhanced_log_message(f"Fetching survey data from: {api_call_url}", "info")
            
            local_survey_dest_folder.mkdir(parents=True, exist_ok=True)
            headers = {"Security-Password": "admin@123"}
            
            response = requests.get(api_call_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            survey_data = response.json()
            
            if 'roads' not in survey_data or not survey_data['roads']:
                self.enhanced_log_message(f"No roads found in API response for survey {survey_id}.", "error")
                return False
            
            self.enhanced_log_message(f"✅ Found {len(survey_data['roads'])} roads in survey data", "info")
            
            # Check if we need to filter roads (for ris and ndd URLs)
            should_filter_roads = any(url in base_api_url for url in ['ris.roadathena.com', 'ndd.roadathena.com'])
            
            # Get selected roads from main app if filtering is needed
            selected_road_ids = []
            if should_filter_roads and hasattr(self.main_app, 'selected_road_ids'):
                selected_road_ids = self.main_app.selected_road_ids
                self.enhanced_log_message(f"🛣️ Road filtering enabled. Processing {len(selected_road_ids)} selected roads", "info")
            
            processed_roads = 0
            skipped_roads = 0
            
            for road_info in survey_data["roads"]:
                if self.cancelled:
                    return False
                
                road_id = road_info.get("id")
                if not road_id:
                    self.enhanced_log_message("Road data found without an ID, skipping.", "warning")
                    continue
                
                # Apply road filtering for ris and ndd URLs
                if should_filter_roads and selected_road_ids and road_id not in selected_road_ids:
                    skipped_roads += 1
                    continue
                
                road_folder = local_survey_dest_folder / f"road_{road_id}"
                road_folder.mkdir(parents=True, exist_ok=True)
                
                gpx_file_url_suffix = road_info.get('gpx_file')
                if gpx_file_url_suffix and self.download_gpx:
                    gpx_filename = f"road_{road_id}.gpx"
                    local_gpx_path = road_folder / gpx_filename
                    
                    if not self.download_gpx_file(gpx_file_url_suffix, local_gpx_path, base_api_url):
                        self.enhanced_log_message(f"Failed to download GPX for road {road_id}. Skipping time extraction for this road.", "error")
                        continue
                    
                    if not self.extract_times_from_gpx(local_gpx_path, road_folder, gpx_time_modify_setting):
                        self.enhanced_log_message(f"Failed to extract times from GPX for road {road_id}.", "warning")
                elif not self.download_gpx:
                    self.enhanced_log_message("Skipping GPX download as per user setting", "info")
                
                processed_roads += 1
            
            # Log road processing summary
            if should_filter_roads:
                self.enhanced_log_message(f"📊 Road processing summary: {processed_roads} processed, {skipped_roads} skipped due to filtering", "info")
            else:
                self.enhanced_log_message(f"📊 Processed {processed_roads} roads", "info")
                
            return processed_roads > 0
            
        except Exception as e:
            self.enhanced_log_message(f"Error in folder structure creation: {str(e)}", "error")
            return False



    def download_gpx_file(self, gpx_url, gpx_file_path, base_api_url):
        """Implementation from Tkinter"""
        try:
            full_gpx_url = gpx_url
            if not gpx_url.startswith("http"):
                full_gpx_url = base_api_url.rstrip('/') + "/" + gpx_url.lstrip('/')
            
            headers = {"Security-Password": "admin@123"}
            response = requests.get(full_gpx_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            gpx_file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(gpx_file_path, 'wb') as f:
                f.write(response.content)
            
            self.enhanced_log_message(f"Downloaded GPX: {gpx_file_path.name}", "success")
            return True
            
        except Exception as e:
            self.enhanced_log_message(f"Failed to download GPX: {str(e)}", "error")
            return False
    
    # def extract_times_from_gpx(self, gpx_file_path, road_folder, gpx_time_modify_setting):
    #     """Implementation from Tkinter - multi-segment version"""
    #     try:
    #         if self.cancelled:
    #             return False
            
    #         tree = ET.parse(str(gpx_file_path))
    #         root = tree.getroot()
            
    #         trkpt_elements = []
    #         for elem in root.findall(".//*"):
    #             if elem.tag.endswith('trkpt'):
    #                 trkpt_elements.append(elem)
            
    #         if not trkpt_elements:
    #             self.enhanced_log_message(f"No <trkpt> elements found in GPX: {gpx_file_path.name}", "warning")
    #             return False
            
    #         times_dt = []
    #         for trkpt_el in trkpt_elements:
    #             time_el = None
    #             for child in trkpt_el:
    #                 if child.tag.endswith('time'):
    #                     time_el = child
    #                     break
                
    #             if time_el is not None and time_el.text:
    #                 try:
    #                     time_str = time_el.text.strip().replace("Z", "")
    #                     dt_obj = None
    #                     try:
    #                         dt_obj = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S.%f")
    #                     except ValueError:
    #                         dt_obj = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S")
    #                     times_dt.append(dt_obj)
    #                 except ValueError as e:
    #                     self.enhanced_log_message(f"Could not parse time from <trkpt>: {e}", "warning")
            
    #         if not times_dt:
    #             self.enhanced_log_message(f"No valid timestamps parsed from <trkpt> elements", "error")
    #             return False
            
    #         times_dt.sort()
            
    #         # Detect gaps in GPS tracking
    #         GAP_THRESHOLD_SECONDS = 30
    #         time_segments = []
    #         current_segment_start = times_dt[0]
            
    #         for i in range(1, len(times_dt)):
    #             time_gap = (times_dt[i] - times_dt[i-1]).total_seconds()
                
    #             if time_gap > GAP_THRESHOLD_SECONDS:
    #                 current_segment_end = times_dt[i-1]
    #                 time_segments.append({
    #                     'start': current_segment_start,
    #                     'end': current_segment_end,
    #                     'gap_after': time_gap
    #                 })
    #                 current_segment_start = times_dt[i]
            
    #         time_segments.append({
    #             'start': current_segment_start,
    #             'end': times_dt[-1],
    #             'gap_after': 0
    #         })
            
    #         # Apply timezone adjustments
    #         adjusted_segments = []
    #         for i, segment in enumerate(time_segments):
    #             start_time_tz_adjusted = segment['start']
    #             end_time_tz_adjusted = segment['end']
                
    #             if gpx_time_modify_setting == "Add_5_30":
    #                 start_time_tz_adjusted += timedelta(hours=5, minutes=30)
    #                 end_time_tz_adjusted += timedelta(hours=5, minutes=30)
    #             elif gpx_time_modify_setting == "Subtract_5_30":
    #                 start_time_tz_adjusted -= timedelta(hours=5, minutes=30)
    #                 end_time_tz_adjusted -= timedelta(hours=5, minutes=30)
                
    #             adjusted_segments.append({
    #                 'start': start_time_tz_adjusted,
    #                 'end': end_time_tz_adjusted,
    #                 'segment_id': i + 1
    #             })
            
    #         # Apply buffers
    #         try:
    #             start_buffer_sec_val = int(self.start_buffer)
    #             end_buffer_sec_val = int(self.end_buffer)
    #         except ValueError:
    #             start_buffer_sec_val = end_buffer_sec_val = 0
            
    #         final_segments = []
    #         for segment in adjusted_segments:
    #             final_start = segment['start'] + timedelta(seconds=start_buffer_sec_val)
    #             final_end = segment['end'] + timedelta(seconds=end_buffer_sec_val)
    #             final_segments.append({
    #                 'start': final_start,
    #                 'end': final_end,
    #                 'segment_id': segment['segment_id']
    #             })
            
    #         # Write times.txt
    #         times_file_path = road_folder / "times.txt"
    #         with open(times_file_path, "w", encoding="utf-8") as f:
    #             if len(final_segments) == 1:
    #                 f.write(f"Start Time: {final_segments[0]['start'].strftime('%Y-%m-%dT%H:%M:%S')}\n")
    #                 f.write(f"End Time: {final_segments[0]['end'].strftime('%Y-%m-%dT%H:%M:%S')}\n")
    #             else:
    #                 f.write(f"Segments: {len(final_segments)}\n")
    #                 for segment in final_segments:
    #                     f.write(f"Segment {segment['segment_id']} Start Time: {segment['start'].strftime('%Y-%m-%dT%H:%M:%S')}\n")
    #                     f.write(f"Segment {segment['segment_id']} End Time: {segment['end'].strftime('%Y-%m-%dT%H:%M:%S')}\n")
            
    #         self.enhanced_log_message(f"Saved {len(final_segments)} time segment(s) for {road_folder.name}", "success")
    #         return True
            
    #     except Exception as e:
    #         self.enhanced_log_message(f"Error extracting times from GPX: {str(e)}", "error")
    #         return False


    def extract_times_from_gpx(self, gpx_file_path, road_folder, gpx_time_modify_setting):
        """Implementation from Tkinter - multi-segment version with improved timestamp parsing"""
        try:
            if self.cancelled:
                return False
            
            tree = ET.parse(str(gpx_file_path))
            root = tree.getroot()
            
            trkpt_elements = []
            for elem in root.findall(".//*"):
                if elem.tag.endswith('trkpt'):
                    trkpt_elements.append(elem)
            
            if not trkpt_elements:
                self.enhanced_log_message(f"No <trkpt> elements found in GPX: {gpx_file_path.name}", "warning")
                return False
            
            times_dt = []
            for trkpt_el in trkpt_elements:
                time_el = None
                for child in trkpt_el:
                    if child.tag.endswith('time'):
                        time_el = child
                        break
                
                if time_el is not None and time_el.text:
                    try:
                        time_str = time_el.text.strip()
                        dt_obj = None
                        
                        # Try multiple parsing methods
                        try:
                            # Method 1: Use dateutil.parser (handles all common formats)
                            dt_obj = dateutil.parser.isoparse(time_str)
                        except (ValueError, AttributeError):
                            # Method 2: Try parsing manually for specific formats
                            # Remove timezone offset for manual parsing
                            time_str_clean = time_str
                            if 'Z' in time_str_clean:
                                time_str_clean = time_str_clean.replace('Z', '+00:00')
                            
                            # Check if it has timezone offset
                            if '+' in time_str_clean or '-' in time_str_clean:
                                # Handle timezone offset manually
                                if '+' in time_str_clean:
                                    time_part, offset = time_str_clean.split('+')
                                    time_str_clean = time_part
                                elif '-' in time_str_clean and time_str_clean.count('-') >= 3:
                                    # Handle negative timezone offset
                                    parts = time_str_clean.rsplit('-', 1)
                                    time_str_clean = parts[0]
                                    # Negative offset will be handled separately if needed
                            
                            # Try different formats
                            try:
                                dt_obj = datetime.strptime(time_str_clean, "%Y-%m-%dT%H:%M:%S.%f")
                            except ValueError:
                                try:
                                    dt_obj = datetime.strptime(time_str_clean, "%Y-%m-%dT%H:%M:%S")
                                except ValueError:
                                    try:
                                        dt_obj = datetime.strptime(time_str_clean, "%Y-%m-%dT%H:%M")
                                    except ValueError:
                                        self.enhanced_log_message(f"Could not parse time format: {time_el.text}", "warning")
                                        continue
                        
                        if dt_obj:
                            # Convert to naive UTC datetime if timezone info is present
                            if dt_obj.tzinfo is not None:
                                dt_obj = dt_obj.astimezone(pytz.UTC).replace(tzinfo=None)
                            times_dt.append(dt_obj)
                        
                    except Exception as e:
                        self.enhanced_log_message(f"Could not parse time from <trkpt>: {e} - Value: {time_el.text}", "warning")
            
            if not times_dt:
                self.enhanced_log_message(f"No valid timestamps parsed from <trkpt> elements", "error")
                return False
            
            times_dt.sort()
            
            # Detect gaps in GPS tracking
            GAP_THRESHOLD_SECONDS = 30
            time_segments = []
            current_segment_start = times_dt[0]
            
            for i in range(1, len(times_dt)):
                time_gap = (times_dt[i] - times_dt[i-1]).total_seconds()
                
                if time_gap > GAP_THRESHOLD_SECONDS:
                    current_segment_end = times_dt[i-1]
                    time_segments.append({
                        'start': current_segment_start,
                        'end': current_segment_end,
                        'gap_after': time_gap
                    })
                    current_segment_start = times_dt[i]
            
            time_segments.append({
                'start': current_segment_start,
                'end': times_dt[-1],
                'gap_after': 0
            })
            
            # Apply timezone adjustments
            adjusted_segments = []
            for i, segment in enumerate(time_segments):
                start_time_tz_adjusted = segment['start']
                end_time_tz_adjusted = segment['end']
                
                if gpx_time_modify_setting == "Add_5_30":
                    start_time_tz_adjusted += timedelta(hours=5, minutes=30)
                    end_time_tz_adjusted += timedelta(hours=5, minutes=30)
                elif gpx_time_modify_setting == "Subtract_5_30":
                    start_time_tz_adjusted -= timedelta(hours=5, minutes=30)
                    end_time_tz_adjusted -= timedelta(hours=5, minutes=30)
                
                adjusted_segments.append({
                    'start': start_time_tz_adjusted,
                    'end': end_time_tz_adjusted,
                    'segment_id': i + 1
                })
            
            # Apply buffers
            try:
                start_buffer_sec_val = int(self.start_buffer)
                end_buffer_sec_val = int(self.end_buffer)
            except ValueError:
                start_buffer_sec_val = end_buffer_sec_val = 0
            
            final_segments = []
            for segment in adjusted_segments:
                final_start = segment['start'] + timedelta(seconds=start_buffer_sec_val)
                final_end = segment['end'] + timedelta(seconds=end_buffer_sec_val)
                final_segments.append({
                    'start': final_start,
                    'end': final_end,
                    'segment_id': segment['segment_id']
                })
            
            # Write times.txt
            times_file_path = road_folder / "times.txt"
            with open(times_file_path, "w", encoding="utf-8") as f:
                if len(final_segments) == 1:
                    f.write(f"Start Time: {final_segments[0]['start'].strftime('%Y-%m-%dT%H:%M:%S')}\n")
                    f.write(f"End Time: {final_segments[0]['end'].strftime('%Y-%m-%dT%H:%M:%S')}\n")
                else:
                    f.write(f"Segments: {len(final_segments)}\n")
                    for segment in final_segments:
                        f.write(f"Segment {segment['segment_id']} Start Time: {segment['start'].strftime('%Y-%m-%dT%H:%M:%S')}\n")
                        f.write(f"Segment {segment['segment_id']} End Time: {segment['end'].strftime('%Y-%m-%dT%H:%M:%S')}\n")
            
            self.enhanced_log_message(f"Saved {len(final_segments)} time segment(s) for {road_folder.name}", "success")
            return True
            
        except Exception as e:
            self.enhanced_log_message(f"Error extracting times from GPX: {str(e)}", "error")
            return False
  
    
    
    
    
    def organize_videos(self, source_videos_folder: Path, survey_processing_folder: Path) -> bool:
        """
        Organizes videos from source_videos_folder into the structure within survey_processing_folder.
        Now supports both single time ranges and multiple discontinuous segments with road filtering.
        """
        self.enhanced_log_message(f"Organizing videos from '{source_videos_folder}' into '{survey_processing_folder}' structure", "info")

        # Check if concatenation is enabled
        concatenate_videos = getattr(self.main_app, 'concatenate_checkbox', None) and self.main_app.concatenate_checkbox.isChecked()
        
        if concatenate_videos:
            self.enhanced_log_message("🔗 Video concatenation is ENABLED", "info")
        
        # Check if we need to filter roads (for ris and ndd URLs)
        should_filter_roads = any(url in getattr(self.main_app, 'dash_url', '') for url in ['ris.roadathena.com', 'ndd.roadathena.com'])
        
        # Get selected roads from main app if filtering is needed
        selected_road_ids = []
        if should_filter_roads and hasattr(self.main_app, 'selected_road_ids'):
            selected_road_ids = self.main_app.selected_road_ids
            self.enhanced_log_message(f"🎯 Road filtering enabled. Will only process videos for {len(selected_road_ids)} selected roads", "info")

        # Track folder statistics and roads with videos
        folder_stats = {
            "total_folders": 0,
            "folders_processed": 0,
            "folders_skipped": 0,
            "folders_with_videos": 0,
            "videos_per_folder": {},
            "folders_concatenated": 0
        }
        
        # Track which roads actually received videos
        roads_with_videos = set()

        # 1. Pre-parse all times.txt files (now supporting multiple segments)
        road_time_ranges = []
        for road_dir in survey_processing_folder.iterdir():
            if self.cancelled: 
                return False
            if road_dir.is_dir() and road_dir.name.startswith("road_"):
                folder_stats["total_folders"] += 1
                
                # Extract road ID from folder name
                try:
                    road_id = int(road_dir.name.replace("road_", ""))
                    
                    # Apply road filtering for ris and ndd URLs
                    if should_filter_roads and selected_road_ids and road_id not in selected_road_ids:
                        self.enhanced_log_message(f"⏭️ Skipping road {road_id} (not in selected roads)", "info")
                        folder_stats["folders_skipped"] += 1
                        continue
                        
                except ValueError:
                    self.enhanced_log_message(f"⚠️ Could not extract road ID from folder: {road_dir.name}", "warning")
                    continue
                
                if road_dir.name in self.main_app.selected_folders_to_skip:
                    self.enhanced_log_message(
                        f"Skipping folder '{road_dir.name}' as per user selection", 
                        "info",
                        {"folder_name": road_dir.name, "action": "skipped"}
                    )
                    folder_stats["folders_skipped"] += 1
                    continue
                
                times_file = road_dir / "times.txt"
                if times_file.exists():
                    try:
                        with open(times_file, "r") as tf:
                            lines = [line.strip() for line in tf.readlines() if line.strip()]
                        
                        if not lines:
                            self.enhanced_log_message(f"Empty times.txt file in {road_dir.name}", "warning")
                            continue
                        
                        # Check if it's the new multi-segment format
                        if lines[0].startswith("Segments:"):
                            # New multi-segment format
                            segment_count = int(lines[0].split(": ")[1])
                            self.enhanced_log_message(f"Found {segment_count} segments in {road_dir.name}", "info")
                            
                            i = 1
                            segment_id = 1
                            while i < len(lines) and segment_id <= segment_count:
                                if lines[i].startswith(f"Segment {segment_id} Start Time:"):
                                    start_time_str = lines[i].split(": ", 1)[1].strip()
                                    if i + 1 < len(lines) and lines[i + 1].startswith(f"Segment {segment_id} End Time:"):
                                        end_time_str = lines[i + 1].split(": ", 1)[1].strip()
                                        
                                        # Handle potential milliseconds
                                        start_time_str = start_time_str.split(".")[0]
                                        end_time_str = end_time_str.split(".")[0]

                                        start_dt = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M:%S")
                                        end_dt = datetime.strptime(end_time_str, "%Y-%m-%dT%H:%M:%S")
                                        
                                        road_time_ranges.append({
                                            "path": road_dir, 
                                            "start": start_dt, 
                                            "end": end_dt,
                                            "segment_id": segment_id,
                                            "road_name": road_dir.name,
                                            "road_id": road_id
                                        })
                                        
                                        self.enhanced_log_message(f"Loaded segment {segment_id} for {road_dir.name}: {start_dt} to {end_dt}", "info")
                                        segment_id += 1
                                        i += 2
                                    else:
                                        self.enhanced_log_message(f"Malformed segment {segment_id} in {road_dir.name}", "warning")
                                        break
                                else:
                                    i += 1
                        else:
                            # Original single time range format
                            if len(lines) >= 2:
                                start_time_str = lines[0].split(": ", 1)[1].strip()
                                end_time_str = lines[1].split(": ", 1)[1].strip()
                                
                                # Handle potential milliseconds
                                start_time_str = start_time_str.split(".")[0]
                                end_time_str = end_time_str.split(".")[0]

                                start_dt = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M:%S")
                                end_dt = datetime.strptime(end_time_str, "%Y-%m-%dT%H:%M:%S")
                                
                                road_time_ranges.append({
                                    "path": road_dir, 
                                    "start": start_dt, 
                                    "end": end_dt,
                                    "segment_id": 1,
                                    "road_name": road_dir.name,
                                    "road_id": road_id
                                })
                                
                                self.enhanced_log_message(f"Loaded single time range for {road_dir.name}: {start_dt} to {end_dt}", "info")
                            else:
                                self.enhanced_log_message(f"Malformed times.txt in {road_dir.name}", "warning")
                                
                    except Exception as e:
                        self.enhanced_log_message(f"Error reading or parsing {times_file}: {e}", "warning")
                
                folder_stats["folders_processed"] += 1
        
        if not road_time_ranges:
            self.enhanced_log_message(f"No valid time ranges found in {survey_processing_folder}. Cannot organize videos.", "error")
            return False
        
        # Log road filtering status
        if should_filter_roads:
            filtered_road_ids = list(set([r['road_id'] for r in road_time_ranges]))
            self.enhanced_log_message(f"🎯 After filtering: Processing {len(filtered_road_ids)} roads with time data", "success")
        
        # 2. Iterate through video files and match
        video_files_to_process = [
            p for p in source_videos_folder.rglob('*') if p.suffix.lower() in self.VIDEO_FILE_FORMATS and p.is_file()
        ]
        
        if not video_files_to_process:
            self.enhanced_log_message(f"No video files found in '{source_videos_folder}'.", "warning")
            return True  # Not an error, just nothing to do

        self.enhanced_log_message(f"Found {len(video_files_to_process)} video files in source. Processing...", "info")
        
        moved_count = 0
        skipped_count = 0
        total_videos = len(video_files_to_process)

        for i, video_path in enumerate(video_files_to_process):
            if self.cancelled:
                self.enhanced_log_message("Video organization cancelled.", "warning")
                return False 

            self.progress_signal.emit(i, total_videos, video_path.name)
            self.enhanced_log_message(f"[{i+1}/{total_videos}] Processing video: {video_path.name}", "info")
            timestamp = None

            try:
                # Extract timestamp based on filename format or metadata
                filename = video_path.name.upper()
                
                # NEW: Check if filename starts with "vid" or "video"
                if filename.startswith("VID"):
                    try:
                        # Check if it's "VIDEO_" format
                        if filename.startswith("VIDEO_"):
                            # Handle "video_YYYYMMDD_HHMMSS" format
                            timestamp, fps = self.extract_timestamp_from_video_filename(video_path.name)
                        else:
                            # Handle original "vid" format - FIXED METHOD NAME
                            timestamp, fps = self.extract_timestamp_from_vid_filename(video_path.name)  # Fixed method name
                        
                        if timestamp:
                            prefix = "video" if filename.startswith("VIDEO_") else "vid"
                            self.enhanced_log_message(f"✅ Extracted timestamp from {prefix} filename: {timestamp}", "success")
                        else:
                            # Fall back to metadata extraction
                            timestamp, _ = self.extract_timestamp_from_metadata(video_path)
                    except Exception as e:
                        self.enhanced_log_message(f"⚠️ Error parsing {video_path.name}: {e}", "warning")
                        # Fall back to metadata extraction
                        timestamp, _ = self.extract_timestamp_from_metadata(video_path)
                
                # Check for MOV files - handle both formats: with underscore and without
                elif video_path.suffix.upper() == ".MOV":
                    try:
                        # Check if filename has underscore format (e.g., "YYYYMMDD_HHMMSS.MOV")
                        if "_" in video_path.stem:
                            date_split, time_split = video_path.stem.split("_")[:2]
                            timestamp = datetime.strptime(date_split + time_split, "%Y%m%d%H%M%S")
                        else:
                            # Handle format without underscore (e.g., "20260105160208.MOV")
                            # Check if it's 14-digit timestamp (YYYYMMDDHHMMSS)
                            if len(video_path.stem) == 14 and video_path.stem.isdigit():
                                timestamp = datetime.strptime(video_path.stem, "%Y%m%d%H%M%S")
                            else:
                                # Try to extract from metadata as fallback
                                timestamp, _ = self.extract_timestamp_from_metadata(video_path)
                        
                        self.enhanced_log_message(f"📅 Extracted timestamp from MOV file {video_path.name}: {timestamp}", "info")
                    except Exception as e:
                        self.enhanced_log_message(f"⚠️ Error parsing MOV file {video_path.name}: {e}", "warning")
                        # Fall back to metadata extraction
                        timestamp, _ = self.extract_timestamp_from_metadata(video_path)
                
                # Existing filename format checks (keep these for other video types)
                elif video_path.suffix.upper() == ".MP4" and \
                    len(video_path.name.split("_")[0]) == 8 and \
                    len(video_path.name.split("_")[1].split(".")[0]) == 6:
                    timestamp, _ = self.extract_timestamp_new_camera(video_path.name)
                elif video_path.name.split("_", 1)[0].isdigit() and \
                    len(video_path.name.split("_", 1)[0]) == 14:
                    video_start_time_str = video_path.name.split("_", 1)[0]
                    timestamp = datetime.strptime(video_start_time_str, "%Y%m%d%H%M%S")
                else:
                    # Fallback to metadata extraction
                    timestamp, _ = self.extract_timestamp_from_metadata(video_path)

                if not timestamp:
                    self.enhanced_log_message(f"Could not extract timestamp for {video_path.name}. Skipping.", "warning")
                    skipped_count += 1
                    continue
                
                self.enhanced_log_message(f"Extracted timestamp for {video_path.name}: {timestamp}", "info")

                # Try to match with any time range (including segments)
                matched = False
                for time_range in road_time_ranges:
                    if self.is_timestamp_in_processing_range(timestamp, time_range["start"], time_range["end"]):
                        destination_folder = time_range["path"]
                        
                        # RENAME LOGIC: If video starts with "vid" or "video", rename to yyyymmdd_hhmmss format
                        is_vidfile = video_path.name.upper().startswith("VID")
                        segments_for_road = [tr for tr in road_time_ranges if tr["path"] == destination_folder]
                        
                        if is_vidfile:
                            try:
                                # Generate new filename in yyyymmdd_hhmmss format
                                new_filename = f"{timestamp.strftime('%Y%m%d_%H%M%S')}{video_path.suffix}"
                                self.enhanced_log_message(f"📝 Renaming vid file to: {new_filename}", "info")
                                destination_path = destination_folder / new_filename
                            except Exception as rename_error:
                                self.enhanced_log_message(f"⚠️ Failed to generate new filename for {video_path.name}: {rename_error}", "warning")
                                destination_path = destination_folder / video_path.name
                        elif len(segments_for_road) > 1:
                            # Multiple segments exist, add segment ID to filename
                            base_name = video_path.stem
                            extension = video_path.suffix
                            new_filename = f"{base_name}_segment{time_range['segment_id']}{extension}"
                            destination_path = destination_folder / new_filename
                            self.enhanced_log_message(f"Multiple segments detected, adding segment ID to filename: {new_filename}", "info")
                        else:
                            destination_path = destination_folder / video_path.name
                        
                        # Handle potential file name conflicts
                        counter = 1
                        original_destination = destination_path
                        while destination_path.exists():
                            base_name = original_destination.stem
                            extension = original_destination.suffix
                            destination_path = destination_folder / f"{base_name}_{counter}{extension}"
                            counter += 1
                        
                        try:
                            # Using shutil.move which is more robust across filesystems
                            shutil.move(str(video_path), str(destination_path))
                            
                            # Track that this road received a video
                            road_id = int(destination_folder.name.replace("road_", ""))
                            roads_with_videos.add(road_id)
                            
                            segment_info = f" (segment {time_range['segment_id']})" if len(segments_for_road) > 1 else ""
                            
                            # Log renaming if it happened
                            if is_vidfile:
                                self.enhanced_log_message(f"✅ MOVED & RENAMED: '{video_path.name}' → '{destination_folder.name}/{destination_path.name}'{segment_info}", "success")
                            else:
                                self.enhanced_log_message(f"✅ MOVED: '{video_path.name}' → '{destination_folder.name}/{destination_path.name}'{segment_info}", "success")
                            
                            moved_count += 1
                            matched = True
                            break  # Move to next video file
                        except Exception as e:
                            self.enhanced_log_message(f"❌ Error moving {video_path.name} to {destination_path}: {e}", "error")
                            skipped_count += 1
                
                if not matched:
                    self.enhanced_log_message(f"❌ No matching time range found for {video_path.name} (Timestamp: {timestamp}). Skipping.", "warning")
                    skipped_count += 1

            except Exception as e:
                self.enhanced_log_message(f"❌ Error processing {video_path.name}: {e}", "error")
                skipped_count += 1
        
        # Store the roads with videos for HTML log generation
        self.roads_with_videos = sorted(list(roads_with_videos))
        
        # Count videos in folders after processing
        for road_dir in survey_processing_folder.iterdir():
            if road_dir.is_dir() and road_dir.name.startswith("road_"):
                video_files = [f for f in road_dir.glob("*") if f.suffix.lower() in self.VIDEO_FILE_FORMATS]
                video_count = len(video_files)
                if video_count > 0:
                    folder_stats["folders_with_videos"] += 1
                    folder_stats["videos_per_folder"][road_dir.name] = video_count
                    
                    # Concatenate videos if enabled and there are multiple videos
                    if concatenate_videos and video_count > 1:
                        concatenation_success = self.concatenate_videos_in_folder(road_dir, video_files)
                        if concatenation_success:
                            folder_stats["folders_concatenated"] += 1
        
        # Log folder statistics
        self.enhanced_log_message(
            "Folder processing completed", 
            "info", 
            {
                "folder_statistics": folder_stats,
                "videos_moved": moved_count,
                "videos_skipped": skipped_count,
                "roads_with_videos": len(roads_with_videos)
            }
        )
        
        self.enhanced_log_message(f"Video organization complete. Moved: {moved_count}, Skipped/Errors: {skipped_count}. Roads with videos: {len(roads_with_videos)}", "info")
        self.progress_signal.emit(total_videos, total_videos, "Video organization complete")
        
        if concatenate_videos and folder_stats["folders_concatenated"] > 0:
            self.enhanced_log_message(f"🔗 Concatenated videos in {folder_stats['folders_concatenated']} folders", "success")
        
        return True

    def concatenate_videos_in_folder(self, folder_path: Path, video_files: list) -> bool:
        """
        Concatenate multiple videos in a folder into a single video
        Videos are sorted by timestamp and concatenated in chronological order
        """
        try:
            self.enhanced_log_message(f"🔗 Concatenating {len(video_files)} videos in folder: {folder_path.name}", "info")
            
            # Get timestamps for each video file and sort
            videos_with_timestamps = []
            for video_file in video_files:
                timestamp = self.get_video_timestamp_for_concatenation(video_file)
                if timestamp:
                    videos_with_timestamps.append((timestamp, video_file))
                else:
                    self.enhanced_log_message(f"⚠️ Could not get timestamp for {video_file.name}, using file creation time", "warning")
                    # Use file creation time as fallback
                    timestamp = datetime.fromtimestamp(video_file.stat().st_ctime)
                    videos_with_timestamps.append((timestamp, video_file))
            
            if not videos_with_timestamps:
                self.enhanced_log_message(f"❌ No valid timestamps found for videos in {folder_path.name}", "error")
                return False
            
            # Sort videos by timestamp (oldest first)
            videos_with_timestamps.sort(key=lambda x: x[0])
            
            # Get earliest timestamp for output filename
            earliest_timestamp = videos_with_timestamps[0][0]
            output_filename = f"{earliest_timestamp.strftime('%Y%m%d_%H%M%S')}.mp4"
            output_path = folder_path / output_filename
            
            # Check if already concatenated
            if output_path.exists():
                self.enhanced_log_message(f"⏩ Concatenated video already exists: {output_filename}", "info")
                return True
            
            # Create text file for ffmpeg concatenation
            concat_list_path = folder_path / "concat_list.txt"
            try:
                with open(concat_list_path, 'w', encoding='utf-8') as f:
                    for _, video_file in videos_with_timestamps:
                        # Escape single quotes in file path for ffmpeg
                        file_path = str(video_file.absolute()).replace("'", "'\\''")
                        f.write(f"file '{file_path}'\n")
                
                # Run ffmpeg concatenation
                self.enhanced_log_message(f"🔄 Concatenating videos using ffmpeg...", "info")
                
                ffmpeg_cmd = [
                    FFMPEG_PATH, '-y', '-f', 'concat', '-safe', '0',
                    '-i', str(concat_list_path),
                    '-c', 'copy',  # Copy codec without re-encoding
                    str(output_path)
                ]
                
                result = subprocess.run(
                    ffmpeg_cmd, 
                    stdout=subprocess.DEVNULL,  # Avoid buffering potentially large output in RAM
                    stderr=subprocess.PIPE, 
                    text=True, 
                    timeout=300  # 5 minute timeout
                )
                
                if result.returncode == 0:
                    self.enhanced_log_message(f"✅ Successfully created concatenated video: {output_filename}", "success")
                    
                    # Verify the output file exists and has content
                    if output_path.exists() and output_path.stat().st_size > 0:
                        # Optionally delete original individual videos
                        delete_originals = True  # Set to True to delete originals
                        if delete_originals:
                            deleted_count = 0
                            for _, video_file in videos_with_timestamps:
                                try:
                                    video_file.unlink()
                                    deleted_count += 1
                                except Exception as e:
                                    self.enhanced_log_message(f"⚠️ Could not delete {video_file.name}: {e}", "warning")
                            
                            self.enhanced_log_message(f"🗑️ Deleted {deleted_count} original video files", "info")
                        
                        # Delete concat list file
                        concat_list_path.unlink()
                        
                        return True
                    else:
                        self.enhanced_log_message(f"❌ Concatenated file creation failed: {output_filename}", "error")
                        return False
                else:
                    self.enhanced_log_message(f"❌ FFmpeg error: {result.stderr}", "error")
                    return False
            
            except subprocess.TimeoutExpired:
                self.enhanced_log_message(f"⏱️ FFmpeg timeout - video files might be too large", "error")
                return False
            except Exception as e:
                self.enhanced_log_message(f"❌ Concatenation error: {e}", "error")
                return False
            
            finally:
                # Clean up concat list file if it exists
                if concat_list_path.exists():
                    try:
                        concat_list_path.unlink()
                    except:
                        pass
        
        except Exception as e:
            self.enhanced_log_message(f"❌ Error in concatenate_videos_in_folder: {e}", "error")
            return False

    def get_video_timestamp_for_concatenation(self, video_path: Path) -> datetime:
        """
        Extract timestamp from video file for concatenation sorting
        """
        try:
            # Try extracting from filename first
            filename = video_path.name.upper()
            
            # Check for vid/video format
            if filename.startswith("VID"):
                try:
                    if filename.startswith("VIDEO_"):
                        timestamp, _ = self.extract_timestamp_from_video_filename(video_path.name)
                    else:
                        timestamp, _ = self.extract_timestamp_from_vid_filename(video_path.name)
                    
                    if timestamp:
                        return timestamp
                except:
                    pass
            
            # Check for MOV files
            if video_path.suffix.upper() == ".MOV":
                try:
                    if "_" in video_path.stem:
                        date_split, time_split = video_path.stem.split("_")[:2]
                        return datetime.strptime(date_split + time_split, "%Y%m%d%H%M%S")
                    elif len(video_path.stem) == 14 and video_path.stem.isdigit():
                        return datetime.strptime(video_path.stem, "%Y%m%d%H%M%S")
                except:
                    pass
            
            # Check for MP4 format with timestamp
            if video_path.suffix.upper() == ".MP4" and \
                len(video_path.name.split("_")[0]) == 8 and \
                len(video_path.name.split("_")[1].split(".")[0]) == 6:
                timestamp, _ = self.extract_timestamp_new_camera(video_path.name)
                if timestamp:
                    return timestamp
            
            # Check for 14-digit timestamp at start
            if video_path.name.split("_", 1)[0].isdigit() and \
                len(video_path.name.split("_", 1)[0]) == 14:
                video_start_time_str = video_path.name.split("_", 1)[0]
                return datetime.strptime(video_start_time_str, "%Y%m%d%H%M%S")
            
            # Fallback to metadata extraction
            timestamp, _ = self.extract_timestamp_from_metadata(video_path)
            return timestamp
            
        except Exception as e:
            self.enhanced_log_message(f"⚠️ Could not extract timestamp for {video_path.name}: {e}", "warning")
            return None        



    def extract_timestamp_from_video_filename(self, video_file_name: str):
        """Extract timestamp from VIDEO_YYYYMMDD_HHMMSS format"""
        try:
            # Remove extension
            filename_without_ext = Path(video_file_name).stem
            
            # Split by underscore - should be ['VIDEO', 'YYYYMMDD', 'HHMMSS']
            parts = filename_without_ext.split('_')
            
            if len(parts) >= 3 and parts[0].upper() == 'VIDEO':
                date_part = parts[1]  # YYYYMMDD
                time_part = parts[2]  # HHMMSS
                
                # Combine and parse
                timestamp = datetime.strptime(date_part + time_part, '%Y%m%d%H%M%S')
                return timestamp, 30  # Default FPS
            return None, None
        except ValueError as e:
            self.enhanced_log_message(f"Could not parse timestamp from VIDEO_ filename: {video_file_name} - {e}", "warning")
            return None, None
        except Exception as e:
            self.enhanced_log_message(f"Error in extract_timestamp_from_video_filename for {video_file_name}: {e}", "error")
            return None, None

    def extract_timestamp_from_vid_filename(self, video_file_name: str):
        """Extract timestamp from VID_YYYYMMDD_HHMMSS format"""
        try:
            # Remove extension
            filename_without_ext = Path(video_file_name).stem
            
            # Split by underscore
            parts = filename_without_ext.split('_')
            
            # Should be at least 3 parts: ['VID', 'YYYYMMDD', 'HHMMSS']
            if len(parts) >= 3 and parts[0].upper() == 'VID':
                date_part = parts[1]  # YYYYMMDD
                time_part = parts[2]  # HHMMSS
                
                # Combine and parse
                timestamp = datetime.strptime(date_part + time_part, '%Y%m%d%H%M%S')
                return timestamp, 30  # Default FPS
            return None, None
        except ValueError as e:
            self.enhanced_log_message(f"Could not parse timestamp from VID_ filename: {video_file_name} - {e}", "warning")
            return None, None
        except Exception as e:
            self.enhanced_log_message(f"Error in extract_timestamp_from_vid_filename for {video_file_name}: {e}", "error")
            return None, None
   

    def extract_timestamp_new_camera(self, video_file_name: str):
        try:
            parts = Path(video_file_name).stem.split("_")
            if len(parts) >= 2:
                date_part, time_part = parts[0], parts[1]
                timestamp = datetime.strptime(date_part + time_part, '%Y%m%d%H%M%S')
                return timestamp, 30  # Default FPS
            return None, None
        except ValueError: # Handles incorrect format in filename
            self.enhanced_log_message(f"Could not parse timestamp from new camera filename: {video_file_name}", "warning")
            return None, None
        except Exception as e:
            self.enhanced_log_message(f"Error in extract_timestamp_new_camera for {video_file_name}: {e}", "error")
            return None, None

    # def extract_timestamp_from_metadata(self, video_path: Path):
    #     """Extracts timestamp and FPS using ExifTool, fallback to pymediainfo."""
    #     try:
    #         # Try ExifTool first
    #         result = subprocess.run([
    #             EXIFTOOL_PATH, '-T', '-api', 'largefilesupport=1', '-MediaCreateDate', '-VideoFrameRate', str(video_path)
    #         ], capture_output=True, text=True, timeout=30)

    #         if result.returncode == 0 and result.stdout.strip():
    #             output_parts = result.stdout.strip().split("\t")
    #             if len(output_parts) >= 1: # MediaCreateDate is primary
    #                 start_time_str = output_parts[0].strip()
    #                 fps_val = None
    #                 if len(output_parts) >= 2 and output_parts[1].strip() not in ['-', '']:
    #                      try:
    #                         fps_val = math.floor(float(output_parts[1].strip()))
    #                      except ValueError:
    #                         self.enhanced_log_message(f"[ExifTool] Non-numeric FPS for {video_path.name}: '{output_parts[1]}'", "warning")

    #                 if start_time_str and start_time_str != '-':
    #                     try:
    #                         # Common ExifTool format: YYYY:MM:DD HH:MM:SS or with timezone
    #                         # Remove timezone part if present, e.g., +05:30 or Z
    #                         if '+' in start_time_str: start_time_str = start_time_str.split('+')[0]
    #                         if '-' in start_time_str and len(start_time_str.split('-')[0]) > 4 : # e.g. 2023:10:27 15:30:00-07:00
    #                              start_time_str = start_time_str.split('-')[0] if start_time_str.rfind('-') > 10 else start_time_str

    #                         start_time_str = start_time_str.replace('Z', '').strip()
                            
    #                         dt_obj = datetime.strptime(start_time_str, "%Y:%m:%d %H:%M:%S")
                            
    #                         # Specific NORM_ file adjustment (from original code)
    #                         # if "SLOW" in video_path.name:
    #                         #     dt_obj += timedelta(hours=8, seconds=9) # Why this specific offset?
    #                         #     self.enhanced_log_message(f"[ExifTool] Applied NORM_ file offset to {video_path.name}", "info")
    #                         # return dt_obj, fps_val if fps_val else 30 # Default FPS if not found
    #                         if "NORM_" in video_path.name or "SLOW" in video_path.name:
    #                             dt_obj += timedelta(hours=8, seconds=9)  # Applied to both NORM_ and SLOW files
    #                             file_type = "NORM_" if "NORM_" in video_path.name else "SLOW"
    #                             self.enhanced_log_message(f"[ExifTool] Applied {file_type} file offset to {video_path.name}", "info")
    #                         return dt_obj, fps_val if fps_val else 30  # Default FPS if not found
    #                     except ValueError as ve:
    #                         self.enhanced_log_message(f"[ExifTool] Timestamp format error for {video_path.name} ('{start_time_str}'): {ve}", "warning")
    #                 else: # No timestamp from exiftool
    #                     self.enhanced_log_message(f"[ExifTool] No MediaCreateDate for {video_path.name}.", "info")
    #             else: # Exiftool ran but output was not as expected
    #                  self.enhanced_log_message(f"[ExifTool] Unexpected output for {video_path.name}: '{result.stdout.strip()}'", "warning")
    #         elif result.returncode !=0 : # Exiftool failed
    #              self.enhanced_log_message(f"[ExifTool] Failed for {video_path.name}. Code: {result.returncode}. Error: {result.stderr.strip()}", "warning")

    #     except FileNotFoundError: # ExifTool not found
    #          pass # Fallback will be tried
    #     except subprocess.TimeoutExpired:
    #         self.enhanced_log_message(f"[ExifTool] Timeout for {video_path.name}", "warning")
    #     except Exception as e:
    #         self.enhanced_log_message(f"[ExifTool] General error for {video_path.name}: {e}", "warning")

    #     # Fallback to pymediainfo (try to resolve libmediainfo locations)
    #     try:
    #         self.enhanced_log_message(f"[Pymediainfo] Trying fallback for {video_path.name}", "info")

    #         def _find_mediainfo_lib():
    #             candidates = []
    #             if MEDIAINFO_LIBRARY_PATH:
    #                 candidates.append(MEDIAINFO_LIBRARY_PATH)
    #             if hasattr(sys, '_MEIPASS'):
    #                 candidates.append(os.path.join(sys._MEIPASS, 'libs', 'libmediainfo.so.0'))
    #                 candidates.append(os.path.join(sys._MEIPASS, 'libs', 'libmediainfo.so'))
    #             candidates.append(str(Path.cwd() / 'libs' / 'libmediainfo.so.0'))
    #             candidates.append(str(Path.cwd() / 'libs' / 'libmediainfo.so'))
    #             candidates.append('/usr/lib/x86_64-linux-gnu/libmediainfo.so.0')
    #             candidates.append('/usr/lib/libmediainfo.so.0')
    #             for p in candidates:
    #                 try:
    #                     if p and Path(p).exists():
    #                         return p
    #                 except Exception:
    #                     continue
    #             return None

    #         lib_path = _find_mediainfo_lib()
    #         if lib_path:
    #             media_info = MediaInfo.parse(str(video_path), library_file=lib_path)
    #         else:
    #             media_info = MediaInfo.parse(str(video_path))

    #         video_track = next((t for t in media_info.tracks if t.track_type == 'Video'), None)
    #         if video_track:
    #             dt_obj = None
    #             date_fields_to_try = ['encoded_date', 'tagged_date', 'recorded_date']
    #             for field_name in date_fields_to_try:
    #                 date_str = getattr(video_track, field_name, None)
    #                 if date_str:
    #                     try:
    #                         date_str = date_str.replace("UTC", "").strip()
    #                         if '+' in date_str:
    #                             date_str = date_str.split('+')[0]
    #                         if '.' in date_str:
    #                             date_str = date_str.split('.')[0]
    #                         for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
    #                             try:
    #                                 dt_obj = datetime.strptime(date_str, fmt)
    #                                 break
    #                             except ValueError:
    #                                 continue
    #                         if dt_obj:
    #                             break
    #                     except Exception as e_parse:
    #                         self.enhanced_log_message(f"[Pymediainfo] Error parsing date string '{date_str}' from {field_name} for {video_path.name}: {e_parse}", "warning")
    #             fps_val = None
    #             if getattr(video_track, 'frame_rate', None):
    #                 try:
    #                     fps_val = math.floor(float(video_track.frame_rate))
    #                 except Exception:
    #                     self.enhanced_log_message(f"[Pymediainfo] Non-numeric FPS for {video_path.name}: {getattr(video_track, 'frame_rate', None)}", "warning")
    #             if dt_obj:
    #                 return dt_obj, fps_val if fps_val else 30
    #             else:
    #                 self.enhanced_log_message(f"[Pymediainfo] No usable date field found for {video_path.name}", "info")
    #         else:
    #             self.enhanced_log_message(f"[Pymediainfo] No video track found for {video_path.name}", "info")

    #     except Exception as e:
    #         self.enhanced_log_message(f"[Pymediainfo] Error for {video_path.name}: {e}", "error")
    #         if 'libmediainfo' in str(e).lower() or 'mediainfo' in str(e).lower():
    #             self.enhanced_log_message(
    #                 "Pymediainfo likely failed due to missing libmediainfo. "
    #                 "Set MEDIAINFO_LIBRARY_PATH env var or bundle libmediainfo in ./libs/ and retry.",
    #                 "warning"
    #             )

    #     return None, None # Ultimate fallback



    # def extract_timestamp_from_metadata(self, video_path: Path):
    #     """
    #     Extracts timestamp and FPS using ExifTool with comprehensive error handling.
    #     Applies +8h9s offset for files starting with NORM_ or SLOW.
    #     """
    #     extracted_timestamp = None
    #     fps_val = None
        
    #     # Log entry
    #     self.enhanced_log_message(f"[ExifTool] Attempting to extract metadata from: {video_path.name}", "info")
        
    #     # ============================
    #     # Step 1: Try ExifTool First
    #     # ============================
    #     try:
    #         self.enhanced_log_message(f"[ExifTool] Running exiftool command on {video_path.name}", "debug")
            
    #         result = subprocess.run([
    #             EXIFTOOL_PATH, '-T', '-api', 'largefilesupport=1', 
    #             '-MediaCreateDate', '-VideoFrameRate', str(video_path)
    #         ], capture_output=True, text=True, timeout=30, encoding='utf-8', errors='ignore')
            
    #         self.enhanced_log_message(f"[ExifTool] Command executed. Return code: {result.returncode}", "debug")
            
    #         if result.returncode == 0 and result.stdout.strip():
    #             output_parts = result.stdout.strip().split("\t")
                
    #             self.enhanced_log_message(f"[ExifTool] Raw output: '{result.stdout.strip()}'", "debug")
    #             self.enhanced_log_message(f"[ExifTool] Parsed parts: {output_parts}", "debug")
                
    #             if len(output_parts) >= 1:
    #                 start_time_str = output_parts[0].strip()
                    
    #                 # Check if timestamp exists
    #                 if start_time_str and start_time_str != '-':
    #                     self.enhanced_log_message(f"[ExifTool] Raw timestamp from file: '{start_time_str}'", "info")
                        
    #                     try:
    #                         # Clean up timestamp string
    #                         # Remove timezone part if present (e.g., +05:30, -07:00, Z)
    #                         if '+' in start_time_str:
    #                             start_time_str = start_time_str.split('+')[0].strip()
    #                             self.enhanced_log_message("[ExifTool] Removed + timezone offset", "debug")
    #                         elif '-' in start_time_str and len(start_time_str.split('-')[0]) > 4:
    #                             # Only split if dash is after time (not in date)
    #                             if start_time_str.rfind('-') > 10:
    #                                 start_time_str = start_time_str.split('-')[0].strip()
    #                             self.enhanced_log_message("[ExifTool] Removed - timezone offset", "debug")
                            
    #                         start_time_str = start_time_str.replace('Z', '').strip()
                            
    #                         self.enhanced_log_message(f"[ExifTool] Cleaned timestamp: '{start_time_str}'", "debug")
                            
    #                         # Parse timestamp with multiple possible formats
    #                         dt_obj = None
    #                         possible_formats = [
    #                             "%Y:%m:%d %H:%M:%S",           # Standard ExifTool
    #                             "%Y-%m-%d %H:%M:%S",           # Alternative format
    #                             "%Y:%m:%d %H:%M:%S.%f",        # With milliseconds
    #                             "%Y-%m-%dT%H:%M:%S",           # ISO format
    #                             "%Y-%m-%dT%H:%M:%S.%f",        # ISO with milliseconds
    #                             "%Y/%m/%d %H:%M:%S",           # Slash date format
    #                         ]
                            
    #                         for fmt in possible_formats:
    #                             try:
    #                                 dt_obj = datetime.strptime(start_time_str, fmt)
    #                                 self.enhanced_log_message(f"[ExifTool] Successfully parsed with format: {fmt}", "success")
    #                                 break
    #                             except ValueError:
    #                                 continue
                            
    #                         if dt_obj:
    #                             # ============================
    #                             # Apply NORM_/SLOW Offset
    #                             # ============================
    #                             video_name = video_path.name.upper()
    #                             if video_name.startswith("NORM_") or video_name.startswith("SLOW"):
    #                                 original_dt = dt_obj
    #                                 dt_obj += timedelta(hours=8, seconds=9)
    #                                 file_type = "NORM_" if video_name.startswith("NORM_") else "SLOW"
                                    
    #                                 self.enhanced_log_message(
    #                                     f"[ExifTool] Applied {file_type} offset: "
    #                                     f"{original_dt.strftime('%Y-%m-%d %H:%M:%S')} -> "
    #                                     f"{dt_obj.strftime('%Y-%m-%d %H:%M:%S')} (+8h 9s)", 
    #                                     "info"
    #                                 )
                                
    #                             extracted_timestamp = dt_obj
                                
    #                             # Extract FPS if available
    #                             if len(output_parts) >= 2 and output_parts[1].strip() not in ['-', '']:
    #                                 fps_str = output_parts[1].strip()
    #                                 try:
    #                                     fps_val = math.floor(float(fps_str))
    #                                     self.enhanced_log_message(f"[ExifTool] Extracted FPS: {fps_val}", "info")
    #                                 except ValueError as fps_err:
    #                                     self.enhanced_log_message(
    #                                         f"[ExifTool] Non-numeric FPS value: '{fps_str}'. Error: {fps_err}", 
    #                                         "warning"
    #                                     )
    #                                     fps_val = 30  # Default
    #                             else:
    #                                 fps_val = 30  # Default
    #                                 self.enhanced_log_message("[ExifTool] No FPS found, using default: 30", "info")
                                
    #                             self.enhanced_log_message(
    #                                 f"[ExifTool] ✅ Successfully extracted timestamp: "
    #                                 f"{extracted_timestamp.strftime('%Y-%m-%d %H:%M:%S')}", 
    #                                 "success"
    #                             )
                                
    #                             return extracted_timestamp, fps_val
    #                         else:
    #                             self.enhanced_log_message(
    #                                 f"[ExifTool] ❌ Could not parse timestamp with any format. "
    #                                 f"String: '{start_time_str}'", 
    #                                 "warning"
    #                             )
    #                     except ValueError as ve:
    #                         self.enhanced_log_message(
    #                             f"[ExifTool] ❌ Timestamp parsing ValueError: {ve}. "
    #                             f"String: '{start_time_str}'", 
    #                             "error"
    #                         )
    #                     except Exception as parse_err:
    #                         self.enhanced_log_message(
    #                             f"[ExifTool] ❌ Unexpected parsing error: {type(parse_err).__name__}: {parse_err}", 
    #                             "error"
    #                         )
    #                 else:
    #                     self.enhanced_log_message("[ExifTool] No timestamp found in exiftool output", "warning")
    #             else:
    #                 self.enhanced_log_message(
    #                     f"[ExifTool] ❌ Unexpected output format. Parts: {len(output_parts)}", 
    #                     "warning"
    #                 )
    #         elif result.returncode != 0:
    #             self.enhanced_log_message(
    #                 f"[ExifTool] ❌ Command failed with return code: {result.returncode}", 
    #                 "error"
    #             )
    #             self.enhanced_log_message(f"[ExifTool] Stderr: {result.stderr[:200]}", "error")
    #         else:
    #             self.enhanced_log_message("[ExifTool] No output from exiftool command", "warning")
                
    #     except FileNotFoundError:
    #         self.enhanced_log_message(
    #             "[ExifTool] ❌ ExifTool not found at path: {EXIFTOOL_PATH}. "
    #             "Please ensure ExifTool is installed and path is correct.", 
    #             "error"
    #         )
    #     except subprocess.TimeoutExpired:
    #         self.enhanced_log_message(
    #             f"[ExifTool] ❌ Timeout after 30 seconds for file: {video_path.name}. "
    #             "File may be too large or corrupted.", 
    #             "error"
    #         )
    #     except PermissionError:
    #         self.enhanced_log_message(
    #             f"[ExifTool] ❌ Permission denied accessing file: {video_path.name}", 
    #             "error"
    #         )
    #     except UnicodeDecodeError:
    #         self.enhanced_log_message(
    #             f"[ExifTool] ❌ Unicode decode error. File may have encoding issues: {video_path.name}", 
    #             "error"
    #         )
    #     except Exception as e:
    #         self.enhanced_log_message(
    #             f"[ExifTool] ❌ Unexpected error: {type(e).__name__}: {e}", 
    #             "error"
    #         )
        
    #     # ============================
    #     # Step 2: Fallback to pymediainfo
    #     # ============================
    #     if not extracted_timestamp:
    #         self.enhanced_log_message("[Pymediainfo] Falling back to pymediainfo...", "info")
            
    #         try:
    #             self.enhanced_log_message(f"[Pymediainfo] Parsing with pymediainfo: {video_path.name}", "debug")
                
    #             def _find_mediainfo_lib():
    #                 """Find libmediainfo library with comprehensive search"""
    #                 candidates = []
                    
    #                 # User specified path
    #                 if MEDIAINFO_LIBRARY_PATH:
    #                     candidates.append(MEDIAINFO_LIBRARY_PATH)
    #                     self.enhanced_log_message(f"[Pymediainfo] Checking user path: {MEDIAINFO_LIBRARY_PATH}", "debug")
                    
    #                 # PyInstaller bundle paths
    #                 if hasattr(sys, '_MEIPASS'):
    #                     candidates.extend([
    #                         os.path.join(sys._MEIPASS, 'libs', 'libmediainfo.so.0'),
    #                         os.path.join(sys._MEIPASS, 'libs', 'libmediainfo.so'),
    #                         os.path.join(sys._MEIPASS, 'libmediainfo.so.0'),
    #                     ])
    #                     self.enhanced_log_message("[Pymediainfo] Checking PyInstaller bundle paths", "debug")
                    
    #                 # Common system paths
    #                 system_paths = [
    #                     str(Path.cwd() / 'libs' / 'libmediainfo.so.0'),
    #                     str(Path.cwd() / 'libs' / 'libmediainfo.so'),
    #                     str(Path.cwd() / 'libmediainfo.so.0'),
    #                     '/usr/lib/x86_64-linux-gnu/libmediainfo.so.0',
    #                     '/usr/lib/libmediainfo.so.0',
    #                     '/usr/local/lib/libmediainfo.so.0',
    #                     '/opt/homebrew/lib/libmediainfo.so.0',  # macOS Homebrew
    #                     'C:\\Program Files\\MediaInfo\\libmediainfo.dll',  # Windows
    #                 ]
                    
    #                 candidates.extend(system_paths)
                    
    #                 for p in candidates:
    #                     try:
    #                         if p and Path(p).exists():
    #                             self.enhanced_log_message(f"[Pymediainfo] Found library: {p}", "success")
    #                             return p
    #                     except Exception as path_err:
    #                         self.enhanced_log_message(f"[Pymediainfo] Path check error for {p}: {path_err}", "debug")
    #                         continue
                    
    #                 return None

    #             lib_path = _find_mediainfo_lib()
                
    #             if lib_path:
    #                 media_info = MediaInfo.parse(str(video_path), library_file=lib_path)
    #                 self.enhanced_log_message(f"[Pymediainfo] Library loaded successfully from: {lib_path}", "info")
    #             else:
    #                 self.enhanced_log_message("[Pymediainfo] No libmediainfo found, using default", "warning")
    #                 media_info = MediaInfo.parse(str(video_path))

    #             if not media_info.tracks:
    #                 self.enhanced_log_message("[Pymediainfo] No tracks found in media file", "error")
    #                 return None, None

    #             # Find video track
    #             video_track = None
    #             for track in media_info.tracks:
    #                 if track.track_type == 'Video':
    #                     video_track = track
    #                     break
                
    #             if not video_track:
    #                 self.enhanced_log_message("[Pymediainfo] No video track found", "error")
    #                 return None, None
                
    #             self.enhanced_log_message(f"[Pymediainfo] Found video track. Available fields: {dir(video_track)}", "debug")
                
    #             # Try to extract timestamp from multiple possible fields
    #             dt_obj = None
    #             date_fields_to_try = [
    #                 'encoded_date', 'tagged_date', 'recorded_date', 
    #                 'origin_timestamp', 'creation_date', 'file_creation_date'
    #             ]
                
    #             for field_name in date_fields_to_try:
    #                 try:
    #                     if hasattr(video_track, field_name):
    #                         date_str = getattr(video_track, field_name, None)
    #                         if date_str:
    #                             self.enhanced_log_message(f"[Pymediainfo] Trying field '{field_name}': {date_str}", "debug")
                                
    #                             # Clean the date string
    #                             date_str = str(date_str).replace("UTC", "").strip()
    #                             if '+' in date_str:
    #                                 date_str = date_str.split('+')[0].strip()
    #                             if '.' in date_str:
    #                                 date_str = date_str.split('.')[0].strip()
                                
    #                             # Try multiple formats
    #                             for fmt in [
    #                                 "%Y-%m-%d %H:%M:%S", 
    #                                 "%Y-%m-%dT%H:%M:%S",
    #                                 "%Y:%m:%d %H:%M:%S",
    #                                 "%Y/%m/%d %H:%M:%S",
    #                                 "%d/%m/%Y %H:%M:%S"
    #                             ]:
    #                                 try:
    #                                     dt_obj = datetime.strptime(date_str, fmt)
    #                                     self.enhanced_log_message(
    #                                         f"[Pymediainfo] ✅ Parsed with format '{fmt}' from field '{field_name}'", 
    #                                         "success"
    #                                     )
    #                                     break
    #                                 except ValueError:
    #                                     continue
                                
    #                             if dt_obj:
    #                                 break
    #                 except Exception as field_err:
    #                     self.enhanced_log_message(
    #                         f"[Pymediainfo] Error reading field '{field_name}': {field_err}", 
    #                         "debug"
    #                     )
                
    #             if dt_obj:
    #                 # Apply NORM_/SLOW Offset for pymediainfo too
    #                 video_name = video_path.name.upper()
    #                 if video_name.startswith("NORM_") or video_name.startswith("SLOW"):
    #                     original_dt = dt_obj
    #                     dt_obj += timedelta(hours=8, seconds=9)
    #                     file_type = "NORM_" if video_name.startswith("NORM_") else "SLOW"
                        
    #                     self.enhanced_log_message(
    #                         f"[Pymediainfo] Applied {file_type} offset: "
    #                         f"{original_dt.strftime('%Y-%m-%d %H:%M:%S')} -> "
    #                         f"{dt_obj.strftime('%Y-%m-%d %H:%M:%S')} (+8h 9s)", 
    #                         "info"
    #                     )
                    
    #                 extracted_timestamp = dt_obj
                    
    #                 # Extract FPS
    #                 fps_val = 30  # Default
    #                 if hasattr(video_track, 'frame_rate'):
    #                     try:
    #                         fps_val = math.floor(float(video_track.frame_rate))
    #                         self.enhanced_log_message(f"[Pymediainfo] Extracted FPS: {fps_val}", "info")
    #                     except Exception as fps_err:
    #                         self.enhanced_log_message(
    #                             f"[Pymediainfo] Error parsing FPS: {video_track.frame_rate}. Error: {fps_err}", 
    #                             "warning"
    #                         )
                    
    #                 self.enhanced_log_message(
    #                     f"[Pymediainfo] ✅ Successfully extracted timestamp: "
    #                     f"{extracted_timestamp.strftime('%Y-%m-%d %H:%M:%S')}", 
    #                     "success"
    #                 )
                    
    #                 return extracted_timestamp, fps_val
    #             else:
    #                 self.enhanced_log_message("[Pymediainfo] ❌ No usable date field found", "error")
    #                 return None, None
                    
    #         except ModuleNotFoundError as mod_err:
    #             self.enhanced_log_message(
    #                 f"[Pymediainfo] ❌ Module not found: {mod_err}. Install with: pip install pymediainfo", 
    #                 "error"
    #             )
    #         except OSError as os_err:
    #             if 'libmediainfo' in str(os_err).lower():
    #                 self.enhanced_log_message(
    #                     f"[Pymediainfo] ❌ libmediainfo library error: {os_err}. "
    #                     "Set MEDIAINFO_LIBRARY_PATH env var to correct library path.", 
    #                     "error"
    #                 )
    #             else:
    #                 self.enhanced_log_message(f"[Pymediainfo] ❌ OS Error: {os_err}", "error")
    #         except Exception as e:
    #             self.enhanced_log_message(
    #                 f"[Pymediainfo] ❌ Unexpected error: {type(e).__name__}: {e}", 
    #                 "error"
    #             )
        
    #     # ============================
    #     # Step 3: Ultimate fallback
    #     # ============================
    #     self.enhanced_log_message(f"❌ All methods failed to extract timestamp from: {video_path.name}", "error")
        
    #     # Log summary of all possible errors
    #     error_summary = """
    #     Possible errors:
    #     1. File may be corrupted or not a valid video file
    #     2. No timestamp metadata embedded in the video
    #     3. Unsupported video format/codec
    #     4. File permissions issue
    #     5. ExifTool not installed or incorrect path
    #     6. libmediainfo library not found
    #     7. Unsupported timestamp format
    #     8. File too large/timeout during processing
    #     """
        
    #     self.enhanced_log_message(error_summary, "warning")
        
    #     return None, None




    #     def is_timestamp_in_processing_range(self, timestamp, adjusted_start_time, adjusted_end_time):
    #         """Check if timestamp is within processing range"""
    #         if timestamp and adjusted_start_time <= timestamp <= adjusted_end_time:
    #             return True
    #         return False

    #     def get_subprocess_result(self, command):
    #         """Helper method to run subprocess commands"""
    #         try:
    #             result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    #             return result
    #         except subprocess.TimeoutExpired:
    #             self.enhanced_log_message(f"Subprocess timeout for command: {' '.join(command)}", "error")
    #             return subprocess.CompletedProcess(command, -1, "", "Timeout")
    #         except Exception as e:
    #             self.enhanced_log_message(f"Subprocess error: {e}", "error")
    #             return subprocess.CompletedProcess(command, -1, "", str(e))


    def extract_timestamp_from_metadata(self, video_path: Path):
        """
        Extracts timestamp and FPS using ExifTool with comprehensive error handling.
        Applies +8h9s offset for files starting with NORM_ or SLOW.
        """
        extracted_timestamp = None
        fps_val = None
        
        # ============================
        # Step 1: Try ExifTool First
        # ============================
        try:
            result = subprocess.run([
                EXIFTOOL_PATH, '-T', '-api', 'largefilesupport=1', 
                '-MediaCreateDate', '-VideoFrameRate', str(video_path)
            ], capture_output=True, text=True, timeout=30, encoding='utf-8', errors='ignore')
            
            if result.returncode == 0 and result.stdout.strip():
                output_parts = result.stdout.strip().split("\t")
                
                if len(output_parts) >= 1:
                    start_time_str = output_parts[0].strip()
                    
                    if start_time_str and start_time_str != '-':
                        try:
                            # Clean up timestamp string
                            if '+' in start_time_str:
                                start_time_str = start_time_str.split('+')[0].strip()
                            elif '-' in start_time_str and len(start_time_str.split('-')[0]) > 4:
                                if start_time_str.rfind('-') > 10:
                                    start_time_str = start_time_str.split('-')[0].strip()
                            
                            start_time_str = start_time_str.replace('Z', '').strip()
                            
                            # Parse timestamp with multiple possible formats
                            dt_obj = None
                            possible_formats = [
                                "%Y:%m:%d %H:%M:%S",
                                "%Y-%m-%d %H:%M:%S",
                                "%Y:%m:%d %H:%M:%S.%f",
                                "%Y-%m-%dT%H:%M:%S",
                                "%Y-%m-%dT%H:%M:%S.%f",
                                "%Y/%m/%d %H:%M:%S",
                            ]
                            
                            for fmt in possible_formats:
                                try:
                                    dt_obj = datetime.strptime(start_time_str, fmt)
                                    break
                                except ValueError:
                                    continue
                            
                            if dt_obj:
                                # Apply NORM_/SLOW Offset
                                video_name = video_path.name.upper()
                                original_time = dt_obj
                                
                                if video_name.startswith("NORM_") or video_name.startswith("SLOW"):
                                    dt_obj += timedelta(hours=8, seconds=9)
                                    file_type = "NORM_" if video_name.startswith("NORM_") else "SLOW"
                                    print(f"Extracted time + 8hr 9sec: {dt_obj.strftime('%Y-%m-%d %H:%M:%S')}")
                                else:
                                    print(f"Extracted time: {dt_obj.strftime('%Y-%m-%d %H:%M:%S')}")
                                
                                extracted_timestamp = dt_obj
                                
                                # Extract FPS
                                if len(output_parts) >= 2 and output_parts[1].strip() not in ['-', '']:
                                    fps_str = output_parts[1].strip()
                                    try:
                                        fps_val = math.floor(float(fps_str))
                                    except ValueError:
                                        fps_val = 30
                                else:
                                    fps_val = 30
                                
                                return extracted_timestamp, fps_val
                            
                        except (ValueError, Exception):
                            pass
        
        except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError, UnicodeDecodeError, Exception):
            pass
        
        # ============================
        # Step 2: Fallback to pymediainfo
        # ============================
        if not extracted_timestamp:
            try:
                def _find_mediainfo_lib():
                    candidates = []
                    
                    if MEDIAINFO_LIBRARY_PATH:
                        candidates.append(MEDIAINFO_LIBRARY_PATH)
                    
                    if hasattr(sys, '_MEIPASS'):
                        candidates.extend([
                            os.path.join(sys._MEIPASS, 'libs', 'libmediainfo.so.0'),
                            os.path.join(sys._MEIPASS, 'libs', 'libmediainfo.so'),
                            os.path.join(sys._MEIPASS, 'libmediainfo.so.0'),
                        ])
                    
                    system_paths = [
                        str(Path.cwd() / 'libs' / 'libmediainfo.so.0'),
                        str(Path.cwd() / 'libs' / 'libmediainfo.so'),
                        str(Path.cwd() / 'libmediainfo.so.0'),
                        '/usr/lib/x86_64-linux-gnu/libmediainfo.so.0',
                        '/usr/lib/libmediainfo.so.0',
                        '/usr/local/lib/libmediainfo.so.0',
                        '/opt/homebrew/lib/libmediainfo.so.0',
                        'C:\\Program Files\\MediaInfo\\libmediainfo.dll',
                    ]
                    
                    candidates.extend(system_paths)
                    
                    for p in candidates:
                        try:
                            if p and Path(p).exists():
                                return p
                        except Exception:
                            continue
                    
                    return None

                lib_path = _find_mediainfo_lib()
                
                if lib_path:
                    media_info = MediaInfo.parse(str(video_path), library_file=lib_path)
                else:
                    media_info = MediaInfo.parse(str(video_path))

                if media_info.tracks:
                    video_track = None
                    for track in media_info.tracks:
                        if track.track_type == 'Video':
                            video_track = track
                            break
                    
                    if video_track:
                        dt_obj = None
                        date_fields_to_try = [
                            'encoded_date', 'tagged_date', 'recorded_date', 
                            'origin_timestamp', 'creation_date', 'file_creation_date'
                        ]
                        
                        for field_name in date_fields_to_try:
                            try:
                                if hasattr(video_track, field_name):
                                    date_str = getattr(video_track, field_name, None)
                                    if date_str:
                                        date_str = str(date_str).replace("UTC", "").strip()
                                        if '+' in date_str:
                                            date_str = date_str.split('+')[0].strip()
                                        if '.' in date_str:
                                            date_str = date_str.split('.')[0].strip()
                                        
                                        for fmt in [
                                            "%Y-%m-%d %H:%M:%S", 
                                            "%Y-%m-%dT%H:%M:%S",
                                            "%Y:%m:%d %H:%M:%S",
                                            "%Y/%m/%d %H:%M:%S",
                                            "%d/%m/%Y %H:%M:%S"
                                        ]:
                                            try:
                                                dt_obj = datetime.strptime(date_str, fmt)
                                                break
                                            except ValueError:
                                                continue
                                        
                                        if dt_obj:
                                            break
                            except Exception:
                                continue
                        
                        if dt_obj:
                            # Apply NORM_/SLOW Offset
                            video_name = video_path.name.upper()
                            original_time = dt_obj
                            
                            if video_name.startswith("NORM_") or video_name.startswith("SLOW"):
                                dt_obj += timedelta(hours=8, seconds=9)
                                file_type = "NORM_" if video_name.startswith("NORM_") else "SLOW"
                                print(f"Extracted time + 8hr 9sec: {dt_obj.strftime('%Y-%m-%d %H:%M:%S')}")
                            else:
                                print(f"Extracted time: {dt_obj.strftime('%Y-%m-%d %H:%M:%S')}")
                            
                            extracted_timestamp = dt_obj
                            
                            # Extract FPS
                            fps_val = 30
                            if hasattr(video_track, 'frame_rate'):
                                try:
                                    fps_val = math.floor(float(video_track.frame_rate))
                                except Exception:
                                    pass
                            
                            return extracted_timestamp, fps_val
            
            except Exception:
                pass
        
        return None, None

        # In the ProcessingThread class, add this method:
    def is_timestamp_in_processing_range(self, timestamp, adjusted_start_time, adjusted_end_time):
        """Check if timestamp is within processing range"""
        if timestamp and adjusted_start_time <= timestamp <= adjusted_end_time:
            return True
        return False



# ---------------- S3 VIEW TAB ----------------
class S3ViewTab(QWidget):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.current_path = ""
        self.breadcrumb_paths = []
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Header Section
        header_widget = QWidget()
        header_widget.setObjectName("s3_header")
        header_widget.setStyleSheet("""
            QWidget#s3_header {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1e3c72, stop:1 #2a5298);
                border-radius: 8px;
                padding: 12px;
            }
        """)
        header_layout = QVBoxLayout(header_widget)
        
        title_label = QLabel("S3 Upload Directory")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: white;
                margin-bottom: 5px;
            }
        """)
        
        subtitle_label = QLabel("View of your specific upload directory")
        subtitle_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #e0e0e0;
            }
        """)
        
        header_layout.addWidget(title_label)
        header_layout.addWidget(subtitle_label)
        layout.addWidget(header_widget)
        
        # Controls Section
        controls_widget = QWidget()
        controls_layout = QHBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        
        # Bucket info
        bucket_label = QLabel("Bucket:")
        bucket_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        
        self.bucket_info = QLabel("Checking...")
        self.bucket_info.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        
        # Refresh button
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 12px;
                background: #27ae60;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #219653;
            }
            QPushButton:disabled {
                background: #95a5a6;
                color: #7f8c8d;
            }
        """)
        self.refresh_btn.clicked.connect(self.refresh_s3_view)
        self.refresh_btn.setEnabled(False)  # Initially disabled
        
        controls_layout.addWidget(bucket_label)
        controls_layout.addWidget(self.bucket_info)
        controls_layout.addStretch()
        controls_layout.addWidget(self.refresh_btn)
        
        layout.addWidget(controls_widget)
        
        # Current Path Display
        path_widget = QWidget()
        path_layout = QHBoxLayout(path_widget)
        path_layout.setContentsMargins(0, 0, 0, 0)
        
        path_label = QLabel("Current Path:")
        path_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        
        self.current_path_label = QLabel("Loading...")
        self.current_path_label.setStyleSheet("color: #3498db; font-size: 12px;")
        self.current_path_label.setWordWrap(True)
        
        path_layout.addWidget(path_label)
        path_layout.addWidget(self.current_path_label, 1)
        
        layout.addWidget(path_widget)
        
        # S3 Content Tree
        tree_container = QWidget()
        tree_container.setStyleSheet("""
            QWidget {
                background: white;
                border: 2px solid #e1e8ed;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        tree_layout = QVBoxLayout(tree_container)
        
        tree_label = QLabel("Upload Directory Contents")
        tree_label.setStyleSheet("font-weight: bold; color: #2c3e50; margin-bottom: 5px;")
        tree_layout.addWidget(tree_label)
        
        self.s3_tree = QTreeWidget()
        self.s3_tree.setHeaderLabels(["Name", "Type", "Size", "Last Modified"])
        self.s3_tree.setStyleSheet("""
            QTreeWidget {
                border: 1px solid #d1d8e0;
                border-radius: 6px;
                background: #f8f9fa;
                alternate-background-color: #e9ecef;
            }
            QTreeWidget::item {
                padding: 5px;
                border-bottom: 1px solid #e9ecef;
            }
            QTreeWidget::item:selected {
                background: #3498db;
                color: white;
            }
            QTreeWidget::item:hover {
                background: #e3f2fd;
            }
        """)
        self.s3_tree.setAlternatingRowColors(True)
        self.s3_tree.header().setStretchLastSection(False)
        self.s3_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.s3_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.s3_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.s3_tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        
        self.s3_tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        
        tree_layout.addWidget(self.s3_tree)
        layout.addWidget(tree_container)
        
        # Status Bar
        self.status_label = QLabel("Initializing...")
        self.status_label.setStyleSheet("""
            QLabel {
                color: #7f8c8d;
                font-size: 11px;
                padding: 5px;
                background: #f8f9fa;
                border: 1px solid #e9ecef;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
        
        # Initialize browser after UI is set up
        QTimer.singleShot(100, self.initialize_browser)

    def refresh_s3_view(self):
        """Manual refresh of S3 view with current survey"""
        try:
            # Clear current view
            self.s3_tree.clear()
            self.status_label.setText("Refreshing S3 view...")
            
            # Reload the upload path
            self.load_upload_path()
            
        except Exception as e:
            self.status_label.setText(f"Refresh error: {str(e)}")


    def initialize_browser(self):
        """Initialize the S3 browser to show only the specific upload path"""
        try:
            # Check if S3 client is available and properly configured
            if (hasattr(self.main_app, 's3_client') and 
                self.main_app.s3_client is not None and
                hasattr(self.main_app, 'AWS_STORAGE_BUCKET_NAME') and
                self.main_app.AWS_STORAGE_BUCKET_NAME):
                
                # Test the connection with a simple operation
                try:
                    self.status_label.setText("Connected to S3 bucket - Loading upload directory...")
                    self.refresh_btn.setEnabled(True)
                    
                    # Load the specific upload path
                    self.load_upload_path()
                    
                    return
                except Exception as test_error:
                    error_msg = f"S3 connection test failed: {str(test_error)}"
                    self.bucket_info.setText("Connection Failed")
                    self.status_label.setText(error_msg)
                    self.refresh_btn.setEnabled(False)
                    self.show_s3_config_help()
                    return
            else:
                # S3 client not properly configured
                self.handle_missing_s3_config()
                
        except Exception as e:
            error_msg = f"Error initializing S3 browser: {str(e)}"
            self.bucket_info.setText("Initialization Error")
            self.status_label.setText(error_msg)
            self.refresh_btn.setEnabled(False)

    
    def load_upload_path(self):
        """Load the specific upload path based on survey data"""
        try:
            # Get values from Survey Data Upload tab - Survey tab is at index 1
            survey_tab = self.main_app.tabs.widget(1)  # index 1 for Survey Data Uploader
            
            # Find the survey combo box in the survey tab
            survey_combo = survey_tab.findChild(QComboBox, "survey_combo")
            
            if not survey_combo:
                self.current_path_label.setText("Survey dropdown not found")
                self.status_label.setText("Please check the Survey Data Upload tab")
                return
            
            # Get the selected survey text and extract ID
            selected_survey_text = survey_combo.currentText().strip()
            if not selected_survey_text or selected_survey_text in ["Loading surveys...", "Select a survey..."]:
                self.current_path_label.setText("Please select a survey in the Survey Data Upload tab")
                self.status_label.setText("Waiting for survey selection...")
                return
            
            # Get survey ID using the main app's method
            survey_id = self.main_app.get_selected_survey_id()
            
            if not survey_id:
                # Alternative: Try to extract from the surveys_dict
                if hasattr(self.main_app, 'surveys_dict') and selected_survey_text in self.main_app.surveys_dict:
                    survey_id = self.main_app.surveys_dict[selected_survey_text]
                else:
                    # Last resort: Try regex extraction from display text
                    import re
                    survey_id_match = re.search(r'\(ID:\s*(\d+)\)', selected_survey_text)
                    if survey_id_match:
                        survey_id = survey_id_match.group(1)
                    else:
                        # If no ID found in text, try to extract numeric part
                        numbers = re.findall(r'\d+', selected_survey_text)
                        if numbers:
                            survey_id = numbers[0]  # Take first number found
                        else:
                            self.current_path_label.setText("Could not extract survey ID")
                            self.status_label.setText("Please select a valid survey with an ID")
                            return
            
            # Get API URL and model type
            api_url = self.main_app.dash_url
            model_type_combo = survey_tab.findChild(QComboBox, "model_combo")
            model_type = model_type_combo.currentText() if model_type_combo else "pavement"
            
            if not survey_id:
                self.current_path_label.setText("Please select a survey in the Survey Data Upload tab")
                self.status_label.setText("Waiting for survey selection...")
                return
            
            # Extract base API name from URL
            if api_url:
                # Handle different URL formats
                if '//' in api_url:
                    base_api_name = api_url.split("//")[1].split(".")[0]
                else:
                    base_api_name = api_url.split(".")[0] if '.' in api_url else "unknown"
            else:
                base_api_name = "unknown"
            
            # Construct the upload path (show processed outputs)
            upload_path = f"input/videos/{model_type}/{base_api_name}/survey_{survey_id}/"
            
            # Update the display and load contents
            self.current_path = upload_path
            self.current_path_label.setText(upload_path)
            self.bucket_info.setText(self.main_app.AWS_STORAGE_BUCKET_NAME)
            
            # Show survey info in status
            survey_name = selected_survey_text.split('(ID:')[0].strip() if '(ID:' in selected_survey_text else selected_survey_text
            self.status_label.setText(f"Loading upload directory for: {survey_name} (ID: {survey_id})")
            
            self.load_s3_contents(upload_path)
            
        except Exception as e:
            self.status_label.setText(f"Error determining upload path: {str(e)}")
            print(f"S3 View Error: {e}")
            # Debug information
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
   
   
   
    def handle_missing_s3_config(self):
        """Handle missing S3 configuration"""
        self.bucket_info.setText("S3 Not Configured")
        self.status_label.setText("S3 client not available. Check AWS credentials in .env file.")
        self.refresh_btn.setEnabled(False)
        
        # Add help text to the tree
        self.s3_tree.clear()
        help_item = QTreeWidgetItem(["S3 Configuration Required", "Help", "", ""])
        help_item.setData(0, Qt.ItemDataRole.UserRole, "help")
        self.s3_tree.addTopLevelItem(help_item)

    def show_s3_config_help(self):
        """Show help message for S3 configuration"""
        help_text = """
        <h3>S3 Configuration Required</h3>
        <p>The S3 browser cannot connect to AWS. Please check:</p>
        <ol>
            <li><b>.env file</b> exists in the application directory with:
                <ul>
                    <li>AWS_ACCESS_KEY_ID=your_access_key</li>
                    <li>AWS_SECRET_ACCESS_KEY=your_secret_key</li>
                    <li>AWS_STORAGE_BUCKET_NAME=your_bucket_name</li>
                    <li>AWS_S3_REGION_NAME=your_region</li>
                </ul>
            </li>
            <li><b>AWS credentials</b> are valid and have S3 permissions</li>
            <li><b>Internet connection</b> is available</li>
        </ol>
        <p>After updating the .env file, restart the application.</p>
        """
        
        # Add help item to tree
        self.s3_tree.clear()
        help_item = QTreeWidgetItem(["Click here for S3 setup instructions", "Help", "", ""])
        help_item.setData(0, Qt.ItemDataRole.UserRole, "help")
        self.s3_tree.addTopLevelItem(help_item)
        
        # Connect double-click to show help
        self.s3_tree.itemDoubleClicked.connect(self.on_help_item_clicked)

    def on_help_item_clicked(self, item, column):
        """Handle click on help item"""
        if item.data(0, Qt.ItemDataRole.UserRole) == "help":
            self.show_configuration_help_dialog()

    def show_configuration_help_dialog(self):
        """Show detailed configuration help dialog"""
        help_dialog = QDialog(self)
        help_dialog.setWindowTitle("S3 Configuration Help")
        help_dialog.setFixedSize(600, 500)
        
        layout = QVBoxLayout(help_dialog)
        
        # Title
        title = QLabel("AWS S3 Configuration Setup")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #2c3e50; margin-bottom: 15px;")
        layout.addWidget(title)
        
        # Scroll area for content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        # Configuration steps
        steps = [
            {
                "title": "1. Create .env File",
                "content": """
                Create a file named <code>.env</code> in the same directory as the application with the following content:
                """,
                "code": """AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_STORAGE_BUCKET_NAME=your-bucket-name
AWS_S3_REGION_NAME=us-east-1"""
            },
            {
                "title": "2. Get AWS Credentials",
                "content": """
                Obtain your AWS credentials from the AWS Management Console:
                <ul>
                    <li>Go to AWS IAM (Identity and Access Management)</li>
                    <li>Create a user with <b>Programmatic access</b></li>
                    <li>Attach the <b>AmazonS3FullAccess</b> policy</li>
                    <li>Copy the Access Key ID and Secret Access Key</li>
                </ul>
                """
            },
            {
                "title": "3. Check Your Bucket",
                "content": """
                Ensure your S3 bucket exists and is accessible:
                <ul>
                    <li>Bucket name matches AWS_STORAGE_BUCKET_NAME in .env</li>
                    <li>Region matches AWS_S3_REGION_NAME in .env</li>
                    <li>Your IAM user has read/write permissions</li>
                </ul>
                """
            },
            {
                "title": "4. Restart Application",
                "content": """
                After creating/updating the .env file, restart the RoadAthena application for changes to take effect.
                """
            }
        ]
        
        for step in steps:
            # Step title
            step_title = QLabel(step["title"])
            step_title.setStyleSheet("font-weight: bold; color: #3498db; margin-top: 15px; margin-bottom: 5px;")
            scroll_layout.addWidget(step_title)
            
            # Step content
            if step["content"]:
                content_label = QLabel(step["content"])
                content_label.setStyleSheet("margin-bottom: 10px; line-height: 1.4;")
                content_label.setWordWrap(True)
                scroll_layout.addWidget(content_label)
            
            # Code block
            if "code" in step:
                code_text = QTextEdit()
                code_text.setPlainText(step["code"])
                code_text.setStyleSheet("""
                    QTextEdit {
                        background-color: #2c3e50;
                        color: #ecf0f1;
                        font-family: 'Courier New', monospace;
                        padding: 10px;
                        border-radius: 5px;
                        border: 1px solid #34495e;
                    }
                """)
                code_text.setReadOnly(True)
                code_text.setFixedHeight(80 if step["title"] == "1. Create .env File" else 60)
                scroll_layout.addWidget(code_text)
        
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("""
            QPushButton {
                padding: 8px 16px;
                background: #3498db;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #2980b9;
            }
        """)
        close_btn.clicked.connect(help_dialog.accept)
        layout.addWidget(close_btn)
        
        help_dialog.exec()
    
    def load_s3_contents(self, prefix):
        """Load S3 contents for the given prefix"""
        if not self.main_app.s3_client:
            self.status_label.setText("S3 client not available")
            self.show_s3_config_help()
            return
            
        self.status_label.setText("Loading upload directory contents...")
        self.refresh_btn.setEnabled(False)
        
        # Clear current tree
        self.s3_tree.clear()
        
        # Start browser thread
        self.browser_thread = S3BrowserThread(
            self.main_app.s3_client,
            self.main_app.AWS_STORAGE_BUCKET_NAME,
            prefix,
            1000,
            ""  # No filter path needed
        )
        self.browser_thread.log_signal.connect(self.handle_browser_log)
        self.browser_thread.data_loaded.connect(self.populate_tree)
        self.browser_thread.finished_signal.connect(self.browser_finished)
        self.browser_thread.start()
    
    def handle_browser_log(self, message, level):
        """Handle browser thread log messages"""
        if level == "error":
            self.status_label.setText(f"Error: {message}")
        else:
            self.status_label.setText(message)
    
    def populate_tree(self, items):
        """Populate tree with S3 items"""
        self.s3_tree.clear()
        
        if not items:
            no_data_item = QTreeWidgetItem(["No files found in upload directory", "", "", ""])
            self.s3_tree.addTopLevelItem(no_data_item)
            return
        
        for item in items:
            name = item['name']
            item_type = item['type']
            size = item['size']
            last_modified = item['last_modified']
            
            # Format size for display
            size_str = self.format_size(size) if size > 0 else ""
            
            # Format last modified
            mod_str = ""
            if last_modified:
                try:
                    if isinstance(last_modified, str):
                        mod_str = last_modified
                    else:
                        mod_str = last_modified.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    mod_str = str(last_modified)
            
            tree_item = QTreeWidgetItem([name, item_type.title(), size_str, mod_str])
            
            # Set icon based on type
            if item_type == 'folder':
                tree_item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon))
            else:
                icon_type = self.style().StandardPixmap.SP_FileIcon
                if item['icon'] == 'video':
                    icon_type = self.style().StandardPixmap.SP_MediaPlay
                elif item['icon'] == 'image':
                    icon_type = self.style().StandardPixmap.SP_FileDialogContentsView
                elif item['icon'] == 'text':
                    icon_type = self.style().StandardPixmap.SP_FileDialogDetailedView
                elif item['icon'] == 'gpx':
                    icon_type = self.style().StandardPixmap.SP_FileDialogDetailedView
                tree_item.setIcon(0, self.style().standardIcon(icon_type))
            
            # Store full path for navigation
            tree_item.setData(0, Qt.ItemDataRole.UserRole, item['path'])
            
            self.s3_tree.addTopLevelItem(tree_item)
        
        self.status_label.setText(f"Loaded {len(items)} items in upload directory")
    
    def browser_finished(self, success, message):
        """Handle browser thread completion"""
        self.refresh_btn.setEnabled(True)
        if not success:
            self.status_label.setText(f"Error: {message}")
    
    def on_item_double_clicked(self, item, column):
        """Handle double-click on tree items"""
        path = item.data(0, Qt.ItemDataRole.UserRole)
        item_type = item.text(1).lower()
        
        if item_type == 'folder':
            # Only allow navigation within the upload path
            if path.startswith(self.current_path):
                self.current_path = path
                self.current_path_label.setText(path)
                self.load_s3_contents(path)
        else:
            # For files, show information
            self.show_file_info(item)
    
    def show_file_info(self, item):
        """Show information about the selected file"""
        path = item.data(0, Qt.ItemDataRole.UserRole)
        name = item.text(0)
        size = item.text(2)
        modified = item.text(3)
        
        info_text = f"""
        <b>File Information</b><br><br>
        <b>Name:</b> {name}<br>
        <b>Path:</b> {path}<br>
        <b>Size:</b> {size}<br>
        <b>Last Modified:</b> {modified}<br><br>
        <i>This is a read-only view. File operations are not available.</i>
        """
        
        QMessageBox.information(self, "File Information", info_text)
    
    def format_size(self, size_bytes):
        """Format file size in human-readable format"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        
        return f"{size_bytes:.2f} {size_names[i]}"
    
    def refresh_browser(self):
        """Refresh the current view with error handling"""
        if not self.main_app.s3_client:
            self.status_label.setText("S3 client not available. Cannot refresh.")
            self.show_s3_config_help()
            return
        
        # Reload the upload path based on current survey data
        self.load_upload_path()




class BulkRoadCreationThread(QThread):
    """Thread for handling bulk road creation without freezing the UI"""
    log_signal = pyqtSignal(str, str)
    progress_signal = pyqtSignal(int, int)  # current, total
    finished_signal = pyqtSignal(dict)
    
    def __init__(self, main_app, folder, code_prefix, base, api_url, created_by_id, assigned_to_id, 
                 ho_id, ro_id, div_id, headers):
        super().__init__()
        self.main_app = main_app
        self.folder = folder
        self.code_prefix = code_prefix
        self.base = base
        self.api_url = api_url
        self.created_by_id = created_by_id
        self.assigned_to_id = assigned_to_id
        self.ho_id = ho_id
        self.ro_id = ro_id
        self.div_id = div_id
        self.headers = headers
        self.cancelled = False

    def run(self):
        start_time = datetime.now()
        successful_uploads = 0
        failed_uploads = 0
        
        # Create log directory
        log_dir = Path.cwd() / "bulk_upload_logs"
        log_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        txt_log_path = log_dir / f"bulk_upload_{timestamp}.txt"
        html_log_path = log_dir / f"bulk_upload_{timestamp}.html"
        
        html_log_entries = []

        def log_to_all_sources(message, level="info"):
            self.log_signal.emit(message, level)
            try:
                with open(txt_log_path, 'a', encoding='utf-8') as f:
                    f.write(f"{message}\n")
            except: pass
            html_log_entries.append({
                "timestamp": datetime.now().isoformat(),
                "level": level,
                "message": message
            })

        log_to_all_sources("=" * 60)
        log_to_all_sources(f"BULK UPLOAD SESSION STARTED - {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        log_to_all_sources("=" * 60)

        files = [f for f in os.listdir(self.folder) if f.lower().endswith(".gpx")]
        files.sort()
        total_files = len(files)
        
        if not files:
            log_to_all_sources("❌ No GPX files found in folder.", "warning")
            self.finished_signal.emit({"success": False, "message": "No GPX files found"})
            return

        log_to_all_sources(f"📊 Found {total_files} GPX files")
        start_index = self.main_app.start_index_input.value()
        
        for idx, filename in enumerate(files, start=start_index):
            if self.cancelled: break
            
            file_path = os.path.join(self.folder, filename)
            log_to_all_sources(f"\n📄 Processing file {idx - start_index + 1}/{total_files}: {filename}")
            
            # Extract road name
            timestamp_pattern = r'^\d{8}-\d{6}\s*-\s*(.+?)\.gpx$'
            match = re.match(timestamp_pattern, filename, re.IGNORECASE)
            road_name = match.group(1).strip() if match else filename.replace(".gpx", "").strip()
            
            # Extract width
            width = 0
            width_match = re.search(r'(\d+(?:\.\d+)?)\s*M\b', road_name, re.IGNORECASE)
            if width_match: width = float(width_match.group(1))
            
            road_code = f"{self.code_prefix}{idx:03d}"
            track_length = self.main_app.calculate_gpx_length(file_path)
            length_km = round(track_length / 1000, 2) if track_length else 0
            
            # Chainage
            if "rhs" in filename.lower():
                start_chainage, end_chainage = str(round(track_length, 2)), "0"
                lhs_side, rhs_side = False, True
            else:
                start_chainage, end_chainage = "0", str(round(track_length, 2))
                lhs_side, rhs_side = True, False

            data = {
                "name": road_name, "code": road_code, "length": length_km, "width": width,
                "thickness": 0, "length_unit": "km", "width_unit": "m", "thickness_unit": "mm",
                "start_chainage": start_chainage, "end_chainage": end_chainage,
                "LHR_side": lhs_side, "RHR_side": rhs_side,
                "created_by": self.created_by_id, "assigned_to": self.assigned_to_id,
                "organisation_name": 1, "ho": self.ho_id, "ro": self.ro_id, "division": self.div_id,
            }

            with open(file_path, "rb") as gpx_file:
                try:
                    res = requests.post(self.api_url, headers=self.headers, data=data, files={"gpx_file": gpx_file}, timeout=30)
                    if res.status_code in [200, 201]:
                        log_to_all_sources(f"   ✅ SUCCESS: {road_name} ({road_code})", "success")
                        successful_uploads += 1
                    else:
                        log_to_all_sources(f"   ❌ FAILED: {road_name} ({road_code}) - Status: {res.status_code}", "error")
                        failed_uploads += 1
                except Exception as e:
                    log_to_all_sources(f"   💥 ERROR: {str(e)}", "error")
                    failed_uploads += 1
            
            self.progress_signal.emit(idx - start_index + 1, total_files)

        # Final Summary
        log_to_all_sources("\n" + "=" * 60)
        log_to_all_sources(f"📊 BULK UPLOAD SUMMARY: {successful_uploads} Succeeded, {failed_uploads} Failed")
        log_to_all_sources("=" * 60)
        
        self.finished_signal.emit({
            "success": True, 
            "successful": successful_uploads, 
            "failed": failed_uploads,
            "txt_log": str(txt_log_path),
            "html_log": str(html_log_path),
            "html_entries": html_log_entries,
            "start_time": start_time,
            "total_files": total_files
        })

    def cancel(self):
        self.cancelled = True

# ---------------- MAIN UI ----------------
class RoadAthenaUI(QWidget):
    def __init__(self, username="User", selected_api_url="", dash_url="", login_data=None):
        super().__init__()
        self.username = username
        self.selected_api_url = selected_api_url
        self.dash_url = dash_url  # Store the dash_url
        self.surveys_dict = {}  # Add this line
        self.selected_road_ids = []  # This will store the selected road IDs

        # Handle login data and authentication token
        self.login_data = login_data or {}
        self.auth_token = self.login_data.get('auth_token', '')
        self.user_data = self.login_data.get('user_data', {})
        
        # If login_data wasn't passed but we have individual parameters
        if not self.auth_token and hasattr(self, 'auth_token_from_login'):
            self.auth_token = getattr(self, 'auth_token_from_login', '')
        
        self.current_survey_id = ""
        self.current_survey_name = ""

        # Debug authentication info
        print(f"🔐 Authentication status:")
        print(f"   - Username: {self.username}")
        print(f"   - Auth token available: {bool(self.auth_token)}")
        print(f"   - Dash URL: {self.dash_url}")
        print(f"   - Selected API URL: {self.selected_api_url}")
            
        self.setWindowTitle(f"RoadAthena Toolkit - Welcome {self.username}")
        self.setGeometry(100, 50, 1400, 700)
        
        self.setMinimumSize(1200, 600)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # Initialize S3 client and other variables
        self.file_move_cancel_event = threading.Event()
        self.upload_cancel_event = threading.Event()
        self.active_s3_upload_futures = []
        self.selected_folders_to_skip = []
        self.s3_client = None
        self.AWS_STORAGE_BUCKET_NAME = None
        
        # Progress Phase Tracking
        self.current_phase = "IDLE"  # IDLE, ORGANIZATION, UPLOAD
        
        # Initialize time settings
        self.current_time_settings = {
            'time_option': 'Not specified',
            'start_buffer': 'Not specified', 
            'end_buffer': 'Not specified'
        }
        
        self.load_environment()
        
        self.setup_ui()

        # UI Liveliness state
        self.ui_tick = 0
        self.is_processing_active = False

        # Initialize and Start Internet Monitor
        self.internet_monitor = InternetMonitor()
        self.internet_monitor.status_signal.connect(self.update_connection_status)
        self.internet_monitor.speed_signal.connect(self.update_realtime_speed_display)
        self.internet_monitor.start()

    def upload_html_log_to_s3(self, html_log_path, survey_id, model_type):
        """Upload HTML log file to S3 bucket"""
        try:
            if not self.s3_client:
                self.log_message("❌ S3 client not available. Cannot upload HTML log.", "error")
                return False

            # Extract base API name from URL
            base_api_name = "unknown"
            if self.dash_url:
                base_api_name = self.dash_url.split("//")[1].split(".")[0]
            elif self.selected_api_url:
                base_api_name = self.selected_api_url.split("//")[1].split(".")[0]

            # Construct S3 key for the HTML log
            log_filename = Path(html_log_path).name
            s3_key = f"input/videos/{model_type}/{base_api_name}/survey_{survey_id}/logs/{log_filename}"

            self.log_message(f"📤 Uploading HTML log to S3: {s3_key}", "info")

            # Upload the file
            with open(html_log_path, 'rb') as file:
                self.s3_client.upload_fileobj(
                    file,
                    self.AWS_STORAGE_BUCKET_NAME,
                    s3_key,
                    ExtraArgs={'ContentType': 'text/html'}
                )

            self.log_message(f"✅ HTML log uploaded successfully to S3: {s3_key}", "success")
            return True

        except Exception as e:
            self.log_message(f"❌ Failed to upload HTML log to S3: {str(e)}", "error")
            return False
                
    def generate_final_html_log(self, success):
        """Generate final HTML log for the processing session and upload to S3"""
        username = self.main_app.username if hasattr(self.main_app, 'username') else "Unknown"
        
        # Use roads_with_videos if available, otherwise fall back to folder scanning
        if hasattr(self, 'roads_with_videos'):
            road_ids = self.roads_with_videos
        else:
            # Fallback: scan folders for roads that have videos
            road_ids = []
            try:
                base_processing_dir = Path.cwd() / "roadathena_processed_data"
                local_survey_dest_folder = base_processing_dir / f"survey_{self.survey_id}"
                
                if local_survey_dest_folder.exists():
                    for item in local_survey_dest_folder.iterdir():
                        if item.is_dir() and item.name.startswith("road_"):
                            # Check if this road folder has any video files
                            video_files = list(item.glob("*"))
                            video_files = [f for f in video_files if f.suffix.lower() in self.VIDEO_FILE_FORMATS]
                            if video_files:  # Only include roads that have videos
                                try:
                                    road_id = int(item.name.replace("road_", ""))
                                    road_ids.append(road_id)
                                except ValueError:
                                    pass
            except Exception as e:
                self.enhanced_log_message(f"Error extracting road IDs: {e}", "warning")
        
        # Get time settings from main app if available
        time_settings = {}
        if hasattr(self.main_app, 'current_time_settings'):
            time_settings = self.main_app.current_time_settings
        else:
            # Fallback to default values
            time_settings = {
                "time_option": "Not specified",
                "start_buffer": "Not specified", 
                "end_buffer": "Not specified"
            }
        
        log_data = {
            "username": username,
            "survey_id": self.survey_id,
            "survey_name": f"Survey {self.survey_id}",
            "start_time": datetime.now().isoformat(),
            "system_info": get_system_info(),
            "time_settings": time_settings,
            "model_type": self.model_type,
            "road_ids": road_ids,
            "entries": self.html_log_entries
        }
        
        # Generate HTML log file
        html_log_path = HTMLLogGenerator.create_html_log(log_data)
        self.enhanced_log_message(f"Session HTML log generated: {html_log_path}", "info")
        
        # Upload to S3
        if hasattr(self.main_app, 'upload_html_log_to_s3'):
            upload_success = self.main_app.upload_html_log_to_s3(html_log_path, self.survey_id, self.model_type)
            if upload_success:
                self.enhanced_log_message("✅ HTML log uploaded to S3 successfully", "success")
            else:
                self.enhanced_log_message("⚠️ HTML log saved locally but failed to upload to S3", "warning")
        else:
            self.enhanced_log_message("ℹ️ HTML log saved locally (S3 upload method not available)", "info")      
    
    def load_environment(self):
        """Load AWS credentials and initialize S3 client, supporting PyInstaller bundle"""
        try:
            # Determine if running as a PyInstaller bundle
            if getattr(sys, 'frozen', False):
                # Running as compiled executable
                base_path = sys._MEIPASS
            else:
                # Running as script
                base_path = os.path.dirname(os.path.abspath(__file__))

            env_path = os.path.join(base_path, '.env')
            if os.path.exists(env_path):
                load_dotenv(dotenv_path=env_path)
                print(f"Loaded .env from: {env_path}")
            else:
                # Try current working directory as fallback
                env_path = Path(".env")
                if env_path.exists():
                    load_dotenv(dotenv_path=env_path)
                    print(f"Loaded .env from CWD: {env_path}")
                else:
                    print("No .env file found in bundle or current directory.")
                    # Create a sample .env file if it doesn't exist
                    self.create_sample_env_file()

            self.AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
            self.AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
            self.AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
            self.AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME')

            if all([self.AWS_ACCESS_KEY_ID, self.AWS_SECRET_ACCESS_KEY, self.AWS_S3_REGION_NAME]):
                try:
                    self.s3_client = boto3.client(
                        's3',
                        region_name=self.AWS_S3_REGION_NAME,
                        aws_access_key_id=self.AWS_ACCESS_KEY_ID,
                        aws_secret_access_key=self.AWS_SECRET_ACCESS_KEY
                    )
                    # Test the connection
                    # self.s3_client.list_buckets()
                    print("S3 client initialized successfully")
                except Exception as e:
                    print(f"Error initializing S3 client: {e}")
                    self.s3_client = None
            else:
                missing = []
                if not self.AWS_ACCESS_KEY_ID: missing.append("AWS_ACCESS_KEY_ID")
                if not self.AWS_SECRET_ACCESS_KEY: missing.append("AWS_SECRET_ACCESS_KEY")
                if not self.AWS_S3_REGION_NAME: missing.append("AWS_S3_REGION_NAME")
                print(f"AWS credentials missing: {', '.join(missing)}. S3 uploads disabled.")
                self.s3_client = None
        except Exception as e:
            print(f"Error loading environment: {e}")
            self.s3_client = None

    def update_system_info(self):
        """Update system information (RAM, Disk)"""
        try:
            # RAM Usage
            ram = psutil.virtual_memory()
            ram_percent = ram.percent
            ram_used = ram.used / (1024 ** 3)
            ram_total = ram.total / (1024 ** 3)
            
            # Disk Usage
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
            disk_used = disk.used / (1024 ** 3)
            disk_total = disk.total / (1024 ** 3)
            
            info_text = f"RAM: {ram_used:.1f}/{ram_total:.1f} GB ({ram_percent}%) | Disk: {disk_used:.1f}/{disk_total:.1f} GB ({disk_percent}%)"
            
            if hasattr(self, 'system_info_label'):
                self.system_info_label.setText(info_text)
                
                # Color coding
                if ram_percent > 90 or disk_percent > 90:
                    self.system_info_label.setStyleSheet("color: #e74c3c; font-weight: bold; font-size: 11px;")
                elif ram_percent > 70 or disk_percent > 70:
                    self.system_info_label.setStyleSheet("color: #f39c12; font-weight: bold; font-size: 11px;")
                else:
                    self.system_info_label.setStyleSheet("color: #ecf0f1; font-weight: bold; font-size: 11px;")
                    
        except Exception as e:
            pass

    def create_sample_env_file(self):
        """Create a sample .env file if it doesn't exist"""
        sample_content = """# AWS S3 Configuration
# Fill in your actual AWS credentials below

AWS_ACCESS_KEY_ID=your_aws_access_key_here
AWS_SECRET_ACCESS_KEY=your_aws_secret_key_here
AWS_STORAGE_BUCKET_NAME=your_bucket_name_here
AWS_S3_REGION_NAME=us-east-1

# How to get these credentials:
# 1. Go to AWS IAM Console
# 2. Create a user with Programmatic access
# 3. Attach AmazonS3FullAccess policy
# 4. Copy the Access Key ID and Secret Access Key
"""
        try:
            with open('.env', 'w') as f:
                f.write(sample_content)
            print("Sample .env file created. Please update with your AWS credentials.")
        except Exception as e:
            print(f"Could not create sample .env file: {e}")
    
    def setup_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Header with user info, logout, and internet status
        header_widget = QWidget()
        header_widget.setObjectName("header_widget")
        header_widget.setStyleSheet("""
            QWidget#header_widget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2c3e50, stop:1 #3498db);
                border-radius: 8px;
                padding: 8px;
            }
        """)
        header_widget.setFixedHeight(80)  # Increased height to accommodate internet status
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(15, 5, 15, 5)
        
        # User info on left
        user_info_layout = QVBoxLayout()
        user_info_layout.setSpacing(2)
        
        user_label = QLabel(f"Welcome, {self.username}")
        user_label.setStyleSheet("font-weight: bold; color: white; font-size: 14px;")
        
        # System Info Label
        self.system_info_label = QLabel("Loading system info...")
        self.system_info_label.setStyleSheet("color: #ecf0f1; font-weight: bold; font-size: 11px;")
        
        user_info_layout.addWidget(user_label)
        user_info_layout.addWidget(self.system_info_label)
        
        # API URL info in center - CHANGED: Use dash_url if available
        api_url_to_display = self.dash_url if self.dash_url else self.selected_api_url
        api_label = QLabel(f"API: {api_url_to_display}")
        api_label.setStyleSheet("color: #f39c12; font-weight: bold; font-size: 12px;")
        
        # Internet status and speed info on right
        status_container = QWidget()
        status_layout = QVBoxLayout(status_container)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(2)
        
        # Internet connection status label
        self.internet_status_label = QLabel("Checking connection...")
        self.internet_status_label.setStyleSheet("color: #f39c12; font-weight: bold; font-size: 12px;")
        
        # Real-time Speed info
        self.realtime_speed_label = QLabel("Network: --/-- Mbps")
        self.realtime_speed_label.setStyleSheet("color: #a8d8ea; font-size: 11px; font-weight: bold;")
        
        status_layout.addWidget(self.internet_status_label)
        status_layout.addWidget(self.realtime_speed_label)
        
        # Logout button on far right
        logout_btn = QPushButton("Logout")
        logout_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 12px;
                background: #e74c3c;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #c0392b;
            }
        """)
        logout_btn.clicked.connect(self.logout)
        
        header_layout.addLayout(user_info_layout)
        header_layout.addStretch()
        header_layout.addWidget(api_label)
        header_layout.addStretch()
        header_layout.addWidget(status_container)
        header_layout.addWidget(logout_btn)
        
        main_layout.addWidget(header_widget)

        # Create Tab Widget with responsive styling
        self.tabs = QTabWidget()
        self.tabs.setObjectName("main_tabs")
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                background: #ecf0f1;
            }
            QTabWidget::tab-bar {
                alignment: center;
            }
            QTabBar::tab {
                background: #95a5a6;
                color: white;
                padding: 12px 24px;
                margin: 2px;
                border-radius: 6px;
                font-weight: bold;
                min-width: 120px;
            }
            QTabBar::tab:selected {
                background: #3498db;
            }
            QTabBar::tab:hover {
                background: #2980b9;
            }
        """)
        
       

        # Tab 2: Bulk Road Creation
        bulk_tab = QWidget()
        bulk_tab.setLayout(self.create_bulk_layout())
        self.tabs.addTab(bulk_tab, "Bulk Road Creation")
        


        # Tab 1: Survey Data Uploader
        survey_tab = QWidget()
        survey_tab.setLayout(self.survey_data_uploader_layout())
        self.tabs.addTab(survey_tab, "Survey Data Uploader")



        # Tab 3: S3 View
        self.s3_view_tab = S3ViewTab(self)
        self.tabs.addTab(self.s3_view_tab, "S3 View")
        
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)
        
        # Setup System Info Timer
        self.system_info_timer = QTimer(self)
        self.system_info_timer.timeout.connect(self.update_system_info)
        self.system_info_timer.start(2000) # Update every 2 seconds
        self.update_system_info() # Initial update

        # UI Heartbeat Timer (for active feedback)
        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.timeout.connect(self.on_ui_heartbeat)
        self.heartbeat_timer.start(500) # Every 500ms
    
    def update_connection_status(self, is_connected, status_message):
        """Update the connection status display"""
        if is_connected:
            self.internet_status_label.setText("Connected")
            self.internet_status_label.setStyleSheet("color: #2ecc71; font-weight: bold; font-size: 12px;")
        else:
            self.internet_status_label.setText(f"{status_message}")
            self.internet_status_label.setStyleSheet("color: #e74c3c; font-weight: bold; font-size: 12px;")
            
    def update_realtime_speed_display(self, speed_text):
        """Update the real-time upload/download speed display"""
        if hasattr(self, 'realtime_speed_label'):
            self.realtime_speed_label.setText(speed_text)
    
    def closeEvent(self, event):
        """Handle application close event"""
        event.accept()
    
    def logout(self):
        reply = QMessageBox.question(self, 'Logout', 
                                   'Are you sure you want to logout?',
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                   QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            # Close the window which will trigger the application to show login again
            self.close()


    # ---------------- Bulk Road Creation Tab ----------------
    def create_bulk_layout(self):
        # Main scroll area for responsive layout
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: #f1f5f9;
                width: 12px;
                margin: 0px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #cbd5e1;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #94a3b8;
            }
        """)
        
        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Main container with styling
        container_widget = QWidget()
        container_widget.setStyleSheet("""
            QWidget {
                background: white;
                border-radius: 12px;
            }
        """)
        main_layout = QVBoxLayout(container_widget)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(20)

        # Common styles matching SDAU tab
        label_style = """
            QLabel {
                font-weight: bold; 
                color: #374151;
                font-size: 13px;
                padding: 5px 0px;
            }
        """
        entry_style = """
            QLineEdit, QComboBox, QSpinBox {
                padding: 10px 12px;
                border: 2px solid #e1e8ed;
                border-radius: 8px;
                background: white;
                font-size: 13px;
                selection-background-color: #3b82f6;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border-color: #3b82f6;
                background: #f8fafc;
            }
            QLineEdit:hover, QComboBox:hover, QSpinBox:hover {
                border-color: #cbd5e1;
            }
        """

        # Title Section
        title_frame = QWidget()
        title_frame.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #8e44ad, stop:0.7 #9b59b6, stop:1 #a569bd);
                border-radius: 8px;
                padding: 15px;
            }
        """)
        title_layout = QVBoxLayout(title_frame)
        title_label = QLabel("Bulk Road Data Uploader")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: white;")
        title_layout.addWidget(title_label)
        subtitle_label = QLabel("Create and upload multiple road entries automatically")
        subtitle_label.setStyleSheet("font-size: 12px; color: #e8d4f7;")
        title_layout.addWidget(subtitle_label)
        main_layout.addWidget(title_frame)

        # Form Fields with Grid Layout (matching SDAU)
        form_fields_container = QWidget()
        form_fields_layout = QGridLayout(form_fields_container)
        form_fields_layout.setContentsMargins(0, 10, 0, 10)
        form_fields_layout.setSpacing(15)
        form_fields_layout.setColumnStretch(1, 1)
        form_fields_layout.setColumnStretch(2, 1)

        row_idx = 0

        # API Server Display
        api_label = QLabel("API Server")
        api_label.setStyleSheet(label_style)
        
        self.bulk_dash_url_display = QLabel(self.dash_url)
        self.bulk_dash_url_display.setStyleSheet("""
            QLabel {
                padding: 10px 12px;
                border: 2px solid #3b82f6;
                border-radius: 8px;
                background: #eff6ff;
                font-size: 13px;
                color: #1e40af;
                font-weight: bold;
            }
        """)
        form_fields_layout.addWidget(api_label, row_idx, 0)
        form_fields_layout.addWidget(self.bulk_dash_url_display, row_idx, 1, 1, 2)
        row_idx += 1

        # Head Office
        ho_label = QLabel("Head Office")
        ho_label.setStyleSheet(label_style)
        self.ho_combo = QComboBox()
        self.ho_combo.setStyleSheet(entry_style)
        form_fields_layout.addWidget(ho_label, row_idx, 0)
        form_fields_layout.addWidget(self.ho_combo, row_idx, 1, 1, 2)
        row_idx += 1

        # Market Committee
        mc_label = QLabel("Market Committee")
        mc_label.setStyleSheet(label_style)
        self.ro_combo = QComboBox()
        self.ro_combo.setStyleSheet(entry_style)
        form_fields_layout.addWidget(mc_label, row_idx, 0)
        form_fields_layout.addWidget(self.ro_combo, row_idx, 1, 1, 2)
        row_idx += 1

        # Sub-Division
        div_label = QLabel("Sub Division")
        div_label.setStyleSheet(label_style)
        self.div_combo = QComboBox()
        self.div_combo.setStyleSheet(entry_style)
        form_fields_layout.addWidget(div_label, row_idx, 0)
        form_fields_layout.addWidget(self.div_combo, row_idx, 1, 1, 2)
        row_idx += 1

        # Created By (Admin Users)
        created_label = QLabel("Created By (Admin)")
        created_label.setStyleSheet(label_style)
        self.created_by_combo = QComboBox()
        self.created_by_combo.setStyleSheet(entry_style)
        form_fields_layout.addWidget(created_label, row_idx, 0)
        form_fields_layout.addWidget(self.created_by_combo, row_idx, 1, 1, 2)
        row_idx += 1

        # Assigned To (JE Users)
        assigned_label = QLabel("Assigned To (JE)")
        assigned_label.setStyleSheet(label_style)
        self.assigned_to_combo = QComboBox()
        self.assigned_to_combo.setStyleSheet(entry_style)
        form_fields_layout.addWidget(assigned_label, row_idx, 0)
        form_fields_layout.addWidget(self.assigned_to_combo, row_idx, 1, 1, 2)
        row_idx += 1

        # Road Code Prefix and Last Code info
        prefix_label = QLabel("Road Code Prefix")
        prefix_label.setStyleSheet(label_style)
        self.prefix_input = QLineEdit("VRN")
        self.prefix_input.setStyleSheet(entry_style)
        
        self.last_code_label = QLabel("Last Code: —")
        self.last_code_label.setStyleSheet("""
            QLabel {
                padding: 4px 8px;
                color: #6366f1;
                background: #eef2ff;
                border: 1px dashed #c7d2fe;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        
        prefix_box = QHBoxLayout()
        prefix_box.addWidget(self.prefix_input, 2)
        prefix_box.addWidget(self.last_code_label, 1)
        
        form_fields_layout.addWidget(prefix_label, row_idx, 0)
        form_fields_layout.addLayout(prefix_box, row_idx, 1, 1, 2)
        row_idx += 1

        # Start Index
        start_label = QLabel("Start Index")
        start_label.setStyleSheet(label_style)
        self.start_index_input = QSpinBox()
        self.start_index_input.setStyleSheet(entry_style)
        self.start_index_input.setRange(0, 9999)
        form_fields_layout.addWidget(start_label, row_idx, 0)
        form_fields_layout.addWidget(self.start_index_input, row_idx, 1, 1, 2)
        row_idx += 1

        # GPX Folder Selector
        folder_label = QLabel("GPX Folder")
        folder_label.setStyleSheet(label_style)
        self.bulk_folder_input = QLineEdit()
        self.bulk_folder_input.setStyleSheet(entry_style)
        self.bulk_folder_input.setPlaceholderText("Select folder containing GPX files...")
        
        browse_btn = QPushButton("Browse")
        browse_btn.setStyleSheet("""
            QPushButton { 
                padding: 10px 16px; 
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f59e0b, stop:1 #d97706); 
                color: white; 
                font-weight: bold; 
                border: none; 
                border-radius: 8px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #d97706, stop:1 #b45309);
            }
        """)
        browse_btn.clicked.connect(self.select_bulk_folder)
        
        folder_box = QHBoxLayout()
        folder_box.addWidget(self.bulk_folder_input)
        folder_box.addWidget(browse_btn)
        
        form_fields_layout.addWidget(folder_label, row_idx, 0)
        form_fields_layout.addLayout(folder_box, row_idx, 1, 1, 2)
        row_idx += 1

        main_layout.addWidget(form_fields_container)

        # Bulk Progress Section
        self.bulk_progress_bar = QProgressBar()
        self.bulk_progress_bar.setFixedHeight(8)
        self.bulk_progress_bar.setTextVisible(False)
        self.bulk_progress_bar.setStyleSheet("""
            QProgressBar { border: none; border-radius: 4px; background: #e2e8f0; }
            QProgressBar::chunk { background: #10b981; border-radius: 4px; }
        """)
        self.bulk_progress_bar.hide()
        main_layout.addWidget(self.bulk_progress_bar)

        # Run Button
        bulk_btn = QPushButton("🚀 Run Bulk Road Creation")
        bulk_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        bulk_btn.setStyleSheet("""
            QPushButton { 
                padding: 15px; 
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #10b981, stop:1 #059669); 
                color: white; 
                font-weight: bold; 
                border: none; 
                border-radius: 12px;
                font-size: 15px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #059669, stop:1 #047857);
            }
            QPushButton:pressed {
                background: #064e3b;
            }
        """)
        bulk_btn.clicked.connect(self.run_bulk_creation)
        main_layout.addWidget(bulk_btn)

        # Log Output
        log_label = QLabel("Upload Log")
        log_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #2c3e50; margin-top: 10px;")
        main_layout.addWidget(log_label)
        
        self.bulk_log = QTextEdit()
        self.bulk_log.setStyleSheet("""
            QTextEdit {
                border: 2px solid #e1e8ed;
                border-radius: 8px;
                background: #1e293b;
                color: #e2e8f0;
                font-family: Consolas, monospace;
                font-size: 10px;
                padding: 12px;
                min-height: 300px;
            }
        """)
        self.bulk_log.setReadOnly(True)
        main_layout.addWidget(self.bulk_log)

        # ---------------- Connect signals ----------------
        self.ho_combo.currentIndexChanged.connect(self.load_market_committees)
        self.ro_combo.currentIndexChanged.connect(self.load_sub_divisions)
        self.ho_combo.currentIndexChanged.connect(self.load_users)
        self.ro_combo.currentIndexChanged.connect(self.load_users)
        self.ho_combo.currentIndexChanged.connect(self.load_largest_road_code)
        self.ro_combo.currentIndexChanged.connect(self.load_largest_road_code)
        self.div_combo.currentIndexChanged.connect(self.load_largest_road_code)


        # Initial load (deferred to keep UI responsive)
        QTimer.singleShot(200, self.load_head_offices)

        layout.addWidget(container_widget)
        scroll_area.setWidget(main_widget)
        
        # Create a container layout for the scroll area
        container_layout = QVBoxLayout()
        container_layout.addWidget(scroll_area)
        
        return container_layout

    def select_bulk_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select GPX Folder for Roads")
        if folder:
            # Debug SSD path
            print(f"📂 Bulk Folder selected via QFileDialog: {folder}")
            path_obj = Path(folder)
            print(f"🔍 Path exists: {path_obj.exists()}")
            print(f"🔍 Is directory: {path_obj.is_dir()}")
            print(f"🔍 Absolute path: {path_obj.absolute()}")
            
            self.bulk_folder_input.setText(folder)

    # ---------------- Load Dropdowns ----------------
    def load_head_offices(self):
        # CHANGED: Use dash_url if available, otherwise fall back to selected_api_url
        base = self.dash_url if self.dash_url else self.selected_api_url
        self.ho_combo.clear()
        try:
            response = requests.get(f"{base}/api/head-offices/", headers=HEADERS, timeout=10)
            if response.status_code == 200:
                for item in response.json():
                    self.ho_combo.addItem(item["name"], item["id"])
                self.bulk_log.append("Head offices loaded successfully")
            else:
                self.bulk_log.append(f"Failed to load head offices: {response.status_code}")
        except requests.exceptions.Timeout:
            self.bulk_log.append("Error loading head offices: request timed out")
        except Exception as e:
            self.bulk_log.append(f"Error loading head offices: {e}")

        # Load market committees for the first HO
        self.load_market_committees()

    def load_market_committees(self):
        # CHANGED: Use dash_url if available, otherwise fall back to selected_api_url
        base = self.dash_url if self.dash_url else self.selected_api_url
        ho_id = self.ho_combo.currentData()
        self.ro_combo.clear()
        if ho_id is None:
            return
        try:
            response = requests.get(f"{base}/api/market-committees/", headers=HEADERS, timeout=10)
            if response.status_code == 200:
                for item in response.json():
                    if item["ho"] == ho_id:
                        self.ro_combo.addItem(item["name"], item["id"])
                self.bulk_log.append("Market committees loaded successfully")
            else:
                self.bulk_log.append(f"Failed to load market committees: {response.status_code}")
        except requests.exceptions.Timeout:
            self.bulk_log.append("Error loading market committees: request timed out")
        except Exception as e:
            self.bulk_log.append(f"Error loading market committees: {e}")

        # Load sub-divisions for the first MC
        self.load_sub_divisions()
        self.load_largest_road_code()


    def load_sub_divisions(self):
        # CHANGED: Use dash_url if available, otherwise fall back to selected_api_url
        base = self.dash_url if self.dash_url else self.selected_api_url
        mc_id = self.ro_combo.currentData()
        self.div_combo.clear()
        if mc_id is None:
            return
        try:
            response = requests.get(f"{base}/api/sub-divisions/", headers=HEADERS, timeout=10)
            if response.status_code == 200:
                for item in response.json():
                    if item["mc"] == mc_id:
                        self.div_combo.addItem(item["sub_division"], item["id"])
                self.bulk_log.append("Sub-divisions loaded successfully")
            else:
                self.bulk_log.append(f"Failed to load sub-divisions: {response.status_code}")
        except requests.exceptions.Timeout:
            self.bulk_log.append("Error loading sub-divisions: request timed out")
        except Exception as e:
            self.bulk_log.append(f"Error loading sub-divisions: {e}")

    def load_largest_road_code(self):
        base = self.dash_url if self.dash_url else self.selected_api_url

        ho_id = self.ho_combo.currentData()
        ro_id = self.ro_combo.currentData()
        div_id = self.div_combo.currentData()

        # Validate selections
        if not ho_id or not ro_id or not div_id:
            self.last_code_label.setText("Last Road Code: —")
            return

        url = f"{base}/api/roads/?ho={ho_id}&ro={ro_id}&division={div_id}"
        headers = {"Security-Password": "admin@123"}

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()

            codes = [item["code"] for item in data if item.get("code") and "_" in item["code"]]

            if not codes:
                self.last_code_label.setText("Last Road Code: None")
                return

            # Extract last integer part
            last_numbers = [int(code.split("_")[-1]) for code in codes if code.split("_")[-1].isdigit()]

            if not last_numbers:
                self.last_code_label.setText("Last Road Code: Invalid format")
                return

            largest_code = max(
                codes,
                key=lambda c: int(c.split("_")[-1])
            )

            self.last_code_label.setText(f"Last Road Code: {largest_code}")

        except Exception as e:
            self.last_code_label.setText("Last Road Code: Error")
            self.bulk_log.append(f"⚠️ Failed to load last road code: {e}")

    

    def load_users(self):
        """Load users for created_by (Admin) and assigned_to (JE) dropdowns"""
        base = self.dash_url if self.dash_url else self.selected_api_url
        ho_name = self.ho_combo.currentText()
        mc_name = self.ro_combo.currentText()
        
        # Clear existing items
        self.created_by_combo.clear()
        self.assigned_to_combo.clear()
        
        try:
            response = requests.get(f"{base}/api/user/", headers=HEADERS, timeout=10)
            if response.status_code == 200:
                users = response.json()
                admin_users = []
                je_users = []
                
                for user in users:
                    # Filter by head office
                    if user.get("ho") == ho_name:
                        # Admin users (user_role contains "Admin" or username ends with "_Admin")
                        if (user.get("user_role") == "AdminUser" or 
                            user.get("username", "").endswith("_Admin") or
                            user.get("username", "").endswith("_admin")):
                            admin_users.append(user)
                        
                        # JE users (user_role is "JE" or username ends with "_JE")
                        elif (user.get("user_role") == "JE" or 
                            user.get("username", "").endswith("_JE") or
                            user.get("username", "").endswith("_je")):
                            # Additional filter by market committee if available
                            if not mc_name or user.get("mc") == mc_name or user.get("mc") is None:
                                je_users.append(user)
                
                # Populate created_by dropdown (Admin users)
                for user in admin_users:
                    display_text = f"{user['username']} ({user['user_role']})"
                    self.created_by_combo.addItem(display_text, user["id"])
                
                # Populate assigned_to dropdown (JE users)
                for user in je_users:
                    display_text = f"{user['username']} ({user['user_role']})"
                    self.assigned_to_combo.addItem(display_text, user["id"])
                
                self.bulk_log.append(f"Loaded {len(admin_users)} admin users and {len(je_users)} JE users")
                
            else:
                self.bulk_log.append(f"Failed to load users: {response.status_code}")
        except Exception as e:
            self.bulk_log.append(f"Error loading users: {e}")

    def run_bulk_creation(self):
        folder = self.bulk_folder_input.text().strip()
        code_prefix = self.prefix_input.text().strip() or "VRN"
        base = self.dash_url if self.dash_url else self.selected_api_url
        api_url = f"{base}/api/roads/"
        
        created_by_id = self.created_by_combo.currentData()
        assigned_to_id = self.assigned_to_combo.currentData()
        ho_id = self.ho_combo.currentData()
        ro_id = self.ro_combo.currentData()
        div_id = self.div_combo.currentData()

        if not folder or not os.path.isdir(folder):
            self.log_message("❌ ERROR: Invalid folder path or no folder selected.", "error")
            return
        if created_by_id is None or assigned_to_id is None:
            self.log_message("❌ ERROR: Please select both 'Created By' and 'Assigned To' users.", "error")
            return

        self.bulk_btn.setEnabled(False)
        self.bulk_progress_bar.show()
        self.bulk_progress_bar.setValue(0)
        
        self.bulk_thread = BulkRoadCreationThread(
            self, folder, code_prefix, base, api_url, created_by_id, assigned_to_id,
            ho_id, ro_id, div_id, HEADERS
        )
        self.bulk_thread.log_signal.connect(self.log_message)
        self.bulk_thread.progress_signal.connect(lambda cur, tot: self.bulk_progress_bar.setValue(int(cur/tot*100) if tot > 0 else 0))
        self.bulk_thread.finished_signal.connect(self.bulk_creation_finished)
        self.bulk_thread.start()

    def bulk_creation_finished(self, result):
        self.bulk_btn.setEnabled(True)
        if result.get("success"):
            completion_msg = f"Bulk upload completed!\n\n" \
                            f"✅ Successful: {result['successful']}\n" \
                            f"❌ Failed: {result['failed']}\n" \
                            f"📈 Success Rate: {(result['successful']/result['total_files']*100):.1f}%\n\n" \
                            f"Log files saved to:\n" \
                            f"• {result['txt_log']}\n" \
                            f"• {result['html_log']}"
            QMessageBox.information(self, "Bulk Upload Complete", completion_msg)
        else:
            QMessageBox.warning(self, "Bulk Upload Failed", result.get("message", "Unknown error"))

            ho_id = self.ho_combo.currentData()
            ro_id = self.ro_combo.currentData()
            div_id = self.div_combo.currentData()
            
            # Calculate track length
            track_length = self.calculate_gpx_length(file_path)
            log_to_all_sources(f"   📏 Raw Track Length: {track_length:.2f} meters")

            # Determine chainage based on filename
            filename_lower = filename.lower()
            if "rhs" in filename_lower:
                start_chainage = str(round(track_length, 2)) if track_length else "0"
                end_chainage = "0"
                lhs_side = False
                rhs_side = True
                chainage_info = f"RHS (Start: {start_chainage}, End: {end_chainage})"
                log_to_all_sources(f"   🔄 Side: RHS")
            else:
                start_chainage = "0"
                end_chainage = str(round(track_length, 2)) if track_length else "0"
                lhs_side = True
                rhs_side = False
                chainage_info = f"LHS (Start: {start_chainage}, End: {end_chainage})"
                log_to_all_sources(f"   🔄 Side: LHS")

            # Convert track_length to kilometers for length field
            length_km = round(track_length / 1000, 2) if track_length else 0
            log_to_all_sources(f"   📊 Final Length: {length_km} km")
            
            # Create description with extracted information
            description_parts = []
            if condition_code:
                description_parts.append(f"Condition: {condition_code}")
            if quality:
                description_parts.append(f"Quality: {quality}")
            
            description = "; ".join(description_parts) if description_parts else ""
            
            data = {
                "name": road_name,
                "code": road_code,
                "description": description,
                "length": length_km,
                "width": width,  # Now using extracted width
                "thickness": 0,
                "length_unit": "km",
                "width_unit": "m",
                "thickness_unit": "mm",
                "special_note": "",
                "start_chainage": start_chainage,
                "end_chainage": end_chainage,
                "start_LatLng": "N/A",
                "end_LatLng": "N/A",
                "LHR_side": lhs_side,
                "RHR_side": rhs_side,
                "created_by": created_by_id,
                "assigned_to": assigned_to_id,
                "organisation_name": 1,
                "ho": ho_id,
                "ro": ro_id,
                "division": div_id,
            }

            # Log the data being sent
            log_to_all_sources(f"   📦 Data payload:")
            log_to_all_sources(f"      - Name: {road_name}")
            log_to_all_sources(f"      - Code: {road_code}")
            log_to_all_sources(f"      - Length: {length_km}km")
            log_to_all_sources(f"      - Width: {width}m")
            log_to_all_sources(f"      - Side: {'LHS' if lhs_side else 'RHS'}")
            log_to_all_sources(f"      - Chainage: {chainage_info}")

            # Log API call attempt
            log_to_all_sources(f"   🚀 Uploading to API...")

            with open(file_path, "rb") as gpx_file:
                files_payload = {"gpx_file": gpx_file}
                try:
                    response = requests.post(api_url, headers=HEADERS, data=data, files=files_payload)
                    
                    if response.status_code in [200, 201]:
                        try:
                            response_data = response.json()
                            road_id = response_data.get('id', 'N/A')
                            log_to_all_sources(f"   ✅ SUCCESS: {road_name} ({road_code})", "success")
                            log_to_all_sources(f"      📍 {chainage_info}")
                            log_to_all_sources(f"      📏 Length: {length_km}km, Width: {width}m")
                            log_to_all_sources(f"      🔗 Road ID: {road_id}")
                            successful_uploads += 1
                        except ValueError:
                            log_to_all_sources(f"   ✅ SUCCESS: {road_name} ({road_code})", "success")
                            log_to_all_sources(f"      📍 {chainage_info}")
                            successful_uploads += 1
                    else:
                        log_to_all_sources(f"   ❌ FAILED: {road_name} ({road_code})", "error")
                        log_to_all_sources(f"      📡 Status: {response.status_code}")
                        # Try to get error details
                        try:
                            error_data = response.json()
                            error_msg = error_data.get('error', error_data.get('detail', response.text[:200]))
                        except:
                            error_msg = response.text[:200]
                        log_to_all_sources(f"      💬 Error: {error_msg}")
                        failed_uploads += 1
                        
                except requests.exceptions.ConnectionError:
                    log_to_all_sources(f"   💥 NETWORK ERROR: Could not connect to server", "error")
                    log_to_all_sources(f"      Please check if the server is running at {base}")
                    failed_uploads += 1
                except requests.exceptions.Timeout:
                    log_to_all_sources(f"   ⏰ TIMEOUT: Request timed out", "error")
                    failed_uploads += 1
                except Exception as e:
                    log_to_all_sources(f"   💥 UNEXPECTED ERROR: {str(e)}", "error")
                    failed_uploads += 1

        # Final summary
        end_time = datetime.now()
        duration = end_time - start_time
        
        log_to_all_sources("\n" + "=" * 60)
        log_to_all_sources("📊 BULK UPLOAD SUMMARY")
        log_to_all_sources("=" * 60)
        log_to_all_sources(f"🕒 Started: {start_time.strftime('%H:%M:%S')}")
        log_to_all_sources(f"🕒 Ended: {end_time.strftime('%H:%M:%S')}")
        log_to_all_sources(f"⏱️ Duration: {duration}")
        log_to_all_sources(f"📁 Total Files: {total_files}")
        log_to_all_sources(f"✅ Successful: {successful_uploads}")
        log_to_all_sources(f"❌ Failed: {failed_uploads}")
        
        success_rate = (successful_uploads/total_files*100) if total_files > 0 else 0
        log_to_all_sources(f"📈 Success Rate: {success_rate:.1f}%")
        log_to_all_sources("=" * 60)

        # Generate HTML log
        self.generate_bulk_html_log(html_log_path, html_log_entries, start_time, total_files, successful_uploads, failed_uploads)
        
        # Show completion message with log file locations
        completion_msg = f"Bulk upload completed!\n\n" \
                        f"✅ Successful: {successful_uploads}\n" \
                        f"❌ Failed: {failed_uploads}\n" \
                        f"📈 Success Rate: {success_rate:.1f}%\n\n" \
                        f"Log files saved to:\n" \
                        f"• {txt_log_path}\n" \
                        f"• {html_log_path}"
        
        QMessageBox.information(self, "Bulk Upload Complete", completion_msg)


    def generate_bulk_html_log(self, html_log_path, log_entries, start_time, total_files, successful_uploads, failed_uploads):
        """Generate HTML log for bulk upload session"""
        try:
            username = self.username
            end_time = datetime.now()
            duration = end_time - start_time
            success_rate = (successful_uploads/total_files*100) if total_files > 0 else 0
            
            # Format duration for display (remove microseconds)
            duration_str = str(duration).split('.')[0]
            
            # Determine success rate class for styling
            success_rate_class = 'success' if success_rate >= 80 else 'warning' if success_rate >= 50 else 'error'
            
            html_content = f"""<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>RoadAthena - Bulk Upload Report</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
            }}
            
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                background: white;
                border-radius: 15px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                overflow: hidden;
            }}
            
            .header {{
                background: linear-gradient(135deg, #2c3e50, #3498db);
                color: white;
                padding: 30px;
                text-align: center;
            }}
            
            .header h1 {{
                font-size: 2.5em;
                margin-bottom: 10px;
                font-weight: 300;
            }}
            
            .header .subtitle {{
                font-size: 1.1em;
                opacity: 0.9;
                margin-bottom: 20px;
            }}
            
            .summary-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin: 20px 0;
                padding: 0 30px;
            }}
            
            .summary-card {{
                background: #f8f9fa;
                padding: 20px;
                border-radius: 10px;
                text-align: center;
                border-left: 4px solid #3498db;
            }}
            
            .summary-card.success {{
                border-left-color: #27ae60;
            }}
            
            .summary-card.warning {{
                border-left-color: #f39c12;
            }}
            
            .summary-card.error {{
                border-left-color: #e74c3c;
            }}
            
            .summary-number {{
                font-size: 2em;
                font-weight: bold;
                margin-bottom: 5px;
            }}
            
            .summary-label {{
                font-size: 0.9em;
                color: #6c757d;
            }}
            
            .log-section {{
                padding: 30px;
            }}
            
            .log-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
                padding-bottom: 15px;
                border-bottom: 2px solid #e9ecef;
            }}
            
            .log-title {{
                font-size: 1.5em;
                color: #2c3e50;
                font-weight: 600;
            }}
            
            .log-entries {{
                max-height: 600px;
                overflow-y: auto;
                border: 1px solid #e9ecef;
                border-radius: 10px;
                padding: 0;
            }}
            
            .log-entry {{
                padding: 15px 20px;
                border-bottom: 1px solid #f8f9fa;
                display: flex;
                align-items: flex-start;
                gap: 15px;
            }}
            
            .log-entry:last-child {{
                border-bottom: none;
            }}
            
            .log-entry:hover {{
                background: #f8f9fa;
            }}
            
            .timestamp {{
                color: #6c757d;
                font-size: 0.85em;
                min-width: 120px;
                font-family: 'Courier New', monospace;
            }}
            
            .level {{
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 0.8em;
                font-weight: 600;
                text-transform: uppercase;
                min-width: 80px;
                text-align: center;
            }}
            
            .level-info {{
                background: #d1ecf1;
                color: #0c5460;
            }}
            
            .level-success {{
                background: #d4edda;
                color: #155724;
            }}
            
            .level-warning {{
                background: #fff3cd;
                color: #856404;
            }}
            
            .level-error {{
                background: #f8d7da;
                color: #721c24;
            }}
            
            .message {{
                flex: 1;
                font-size: 0.95em;
                line-height: 1.5;
                word-wrap: break-word;
            }}
            
            .footer {{
                background: #2c3e50;
                color: white;
                text-align: center;
                padding: 20px;
                font-size: 0.9em;
            }}
            
            /* Scrollbar styling */
            .log-entries::-webkit-scrollbar {{
                width: 8px;
            }}
            
            .log-entries::-webkit-scrollbar-track {{
                background: #f1f1f1;
                border-radius: 0 10px 10px 0;
            }}
            
            .log-entries::-webkit-scrollbar-thumb {{
                background: #c1c1c1;
                border-radius: 4px;
            }}
            
            .log-entries::-webkit_scrollbar-thumb:hover {{
                background: #a8a8a8;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>RoadAthena Bulk Upload Report</h1>
                <div class="subtitle">Bulk Road Data Upload Session</div>
            </div>
            
            <div class="summary-grid">
                <div class="summary-card">
                    <div class="summary-number">{total_files}</div>
                    <div class="summary-label">Total Files</div>
                </div>
                <div class="summary-card success">
                    <div class="summary-number">{successful_uploads}</div>
                    <div class="summary-label">Successful</div>
                </div>
                <div class="summary-card error">
                    <div class="summary-number">{failed_uploads}</div>
                    <div class="summary-label">Failed</div>
                </div>
                <div class="summary-card {success_rate_class}">
                    <div class="summary-number">{success_rate:.1f}%</div>
                    <div class="summary-label">Success Rate</div>
                </div>
            </div>
            
            <div class="log-section">
                <div class="log-header">
                    <div class="log-title">Upload Log</div>
                    <div class="log-meta">
                        <small>User: {username} | Duration: {duration_str}</small>
                    </div>
                </div>
                
                <div class="log-entries">
    """
            
            # Add log entries
            for entry in log_entries:
                timestamp = entry.get('timestamp', '')
                level = entry.get('level', 'info')
                message = entry.get('message', '')
                
                # Convert level to CSS class
                level_class = f"level-{level}"
                
                # Format timestamp for display
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    display_time = dt.strftime("%H:%M:%S")
                except:
                    display_time = timestamp
                
                html_content += f"""
                    <div class="log-entry">
                        <div class="timestamp">{display_time}</div>
                        <div class="level {level_class}">{level.upper()}</div>
                        <div class="message">{message}</div>
                    </div>
                """
            
            html_content += f"""
                </div>
            </div>
            
            <div class="footer">
                Generated by RoadAthena Toolkit • {end_time.strftime('%Y-%m-%d %H:%M:%S')}
            </div>
        </div>
    </body>
    </html>"""

            # Write HTML file
            with open(html_log_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
                
            # Log success message
            self.bulk_log.append(f"\n📄 HTML log generated: {html_log_path}")
            
        except Exception as e:
            self.bulk_log.append(f"❌ Error generating HTML log: {e}")

    def calculate_gpx_length(self, gpx_file_path):
        """Calculate the length of a GPX track in meters with detailed logging"""
        try:
            with open(gpx_file_path, 'r', encoding='utf-8') as f:
                gpx_data = gpxpy.parse(f)
            
            total_length = 0
            track_count = 0
            segment_count = 0
            
            for track in gpx_data.tracks:
                track_count += 1
                for segment in track.segments:
                    segment_count += 1
                    segment_length = segment.length_2d()  # Returns length in meters
                    if segment_length:
                        total_length += segment_length
            
            # Log calculation details
            self.bulk_log.append(f"      📐 GPX Analysis: {track_count} tracks, {segment_count} segments")
            self.bulk_log.append(f"      📏 Calculated Length: {total_length:.2f} meters")
            
            return total_length
        
        except Exception as e:
            self.bulk_log.append(f"      ⚠️ WARNING: Could not calculate length: {e}")
            return 0  # Return 0 if calculation fails

    # ---------------- Survey Data Uploader Tab ----------------
    def survey_data_uploader_layout(self):
        try:
            layout = QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            
            # Main container with gradient background
            main_widget = QWidget()
            main_widget.setObjectName("main_widget")
            main_widget.setStyleSheet("""
                QWidget#main_widget {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #f8fafc, stop:1 #e2e8f0);
                }
            """)
            main_layout = QVBoxLayout(main_widget)
            main_layout.setContentsMargins(0, 0, 0, 0)
            main_layout.setSpacing(0)
            
            # --- Header Section with Gradient ---
            header_widget = QWidget()
            header_widget.setObjectName("header_widget")
            header_widget.setStyleSheet("""
                QWidget#header_widget {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #3498db, stop:0.7 #2980b9, stop:1 #1f618d);
                    border-bottom: 2px solid #1a5276;
                }
            """)
            header_widget.setFixedHeight(100)
            header_layout = QVBoxLayout(header_widget)
            header_layout.setContentsMargins(25, 15, 25, 15)
            
            # Title and version
            title_container = QWidget()
            title_layout = QHBoxLayout(title_container)
            title_layout.setContentsMargins(0, 0, 0, 0)
            
            # Icon and title
            title_icon = QLabel("")
            title_icon.setStyleSheet("font-size: 28px; font-weight: bold; color: white;")
            title_icon.setFixedSize(36, 36)
            title_layout.addWidget(title_icon)
            
            title_texts = QWidget()
            title_texts_layout = QVBoxLayout(title_texts)
            title_texts_layout.setContentsMargins(10, 0, 0, 0)
            
            title_label = QLabel("Survey Data Uploader")
            title_label.setObjectName("title_label")
            title_label.setStyleSheet("""
                QLabel#title_label {
                    font-size: 24px;
                    font-weight: bold;
                    color: white;
                    background: transparent;
                }
            """)
            
            version_label = QLabel("v2.0.1 • Professional Data Processing Suite")
            version_label.setObjectName("version_label")
            version_label.setStyleSheet("""
                QLabel#version_label {
                    font-size: 11px;
                    color: #e8f4fd;
                    background: transparent;
                    font-weight: normal;
                }
            """)
            
            title_texts_layout.addWidget(title_label)
            title_texts_layout.addWidget(version_label)
            title_layout.addWidget(title_texts)
            title_layout.addStretch()
            
            header_layout.addWidget(title_container)
            main_layout.addWidget(header_widget)
            
            # --- Main Content Area ---
            content_widget = QWidget()
            content_widget.setObjectName("content_widget")
            content_layout = QVBoxLayout(content_widget)
            content_layout.setContentsMargins(20, 20, 20, 20)
            content_layout.setSpacing(20)
            
            # --- Upload Card ---
            upload_card = QWidget()
            upload_card.setObjectName("upload_card")
            upload_card.setStyleSheet("""
                QWidget#upload_card {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #ffffff, stop:1 #f8f9fa);
                    border: 2px solid #e1e8ed;
                    border-radius: 12px;
                    margin: 5px;
                }
            """)
            upload_card.setFixedHeight(100)
            upload_layout = QVBoxLayout(upload_card)
            upload_layout.setContentsMargins(25, 15, 25, 15)
            
            upload_title = QLabel("Upload Survey Data")
            upload_title.setObjectName("upload_title")
            upload_title.setStyleSheet("""
                QLabel#upload_title {
                    font-size: 18px;
                    font-weight: bold;
                    color: #2c3e50;
                    margin-bottom: 5px;
                }
            """)
            
            upload_desc = QLabel("Complete the form below to process and upload survey data. Ensure all required fields are filled for successful processing.")
            upload_desc.setObjectName("upload_desc")
            upload_desc.setStyleSheet("""
                QLabel#upload_desc {
                    color: #5d6d7e;
                    font-size: 12px;
                    line-height: 1.4;
                }
            """)
            upload_desc.setWordWrap(True)
            
            upload_layout.addWidget(upload_title)
            upload_layout.addWidget(upload_desc)
            content_layout.addWidget(upload_card)
            
            # --- Scrollable Form Area ---
            scroll_area = QScrollArea()
            scroll_area.setObjectName("scroll_area")
            scroll_area.setWidgetResizable(True)
            scroll_area.setFrameShape(QFrame.Shape.NoFrame)
            scroll_area.setStyleSheet("""
                QScrollArea#scroll_area {
                    background: transparent;
                    border: none;
                }
                QScrollBar:vertical {
                    background: #f1f5f9;
                    width: 12px;
                    margin: 0px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background: #cbd5e1;
                    border-radius: 6px;
                    min-height: 20px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #94a3b8;
                }
            """)
            
            scroll_content = QWidget()
            scroll_content.setObjectName("scroll_content")
            scroll_layout = QVBoxLayout(scroll_content)
            scroll_layout.setContentsMargins(0, 0, 0, 0)
            scroll_layout.setSpacing(15)
            
            # --- Form Card ---
            form_card = QWidget()
            form_card.setObjectName("form_card")
            form_card.setStyleSheet("""
                QWidget#form_card {
                    background: white;
                    border: 2px solid #e1e8ed;
                    border-radius: 12px;
                    margin: 5px;
                }
            """)
            form_layout = QVBoxLayout(form_card)
            form_layout.setContentsMargins(0, 0, 0, 0)
            
            # Card Header with Icon
            card_header = QWidget()
            card_header.setObjectName("card_header")
            card_header.setStyleSheet("""
                QWidget#card_header {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #f8fafc, stop:1 #e2e8f0);
                    border-bottom: 2px solid #e1e8ed;
                    border-top-left-radius: 12px;
                    border-top-right-radius: 12px;
                    padding: 15px;
                }
            """)
            header_layout_card = QHBoxLayout(card_header)
            header_layout_card.setContentsMargins(20, 10, 20, 10)
            
            card_icon = QLabel("Survey")
            card_icon.setStyleSheet("font-size: 16px; font-weight: bold;")
            
            card_title = QLabel("Information")
            card_title.setObjectName("card_title")
            card_title.setStyleSheet("""
                QLabel#card_title {
                    font-size: 16px;
                    font-weight: bold;
                    color: #2c3e50;
                }
            """)
            
            header_layout_card.addWidget(card_icon)
            header_layout_card.addWidget(card_title)
            header_layout_card.addStretch()
            
            form_layout.addWidget(card_header)
            
            # Form Fields Container
            form_fields = QWidget()
            form_fields.setObjectName("form_fields")
            form_fields_layout = QGridLayout(form_fields)
            form_fields_layout.setContentsMargins(25, 25, 25, 25)
            form_fields_layout.setVerticalSpacing(12)
            form_fields_layout.setHorizontalSpacing(15)
            
            row_idx = 0
            
            # Styling
            label_style = """
                QLabel {
                    font-weight: bold; 
                    color: #374151;
                    font-size: 13px;
                    padding: 5px 0px;
                }
            """
            entry_style = """
                QLineEdit, QComboBox {
                    padding: 10px 12px;
                    border: 2px solid #e1e8ed;
                    border-radius: 8px;
                    background: white;
                    font-size: 13px;
                    selection-background-color: #3b82f6;
                }
                QLineEdit:focus, QComboBox:focus {
                    border-color: #3b82f6;
                    background: #f8fafc;
                }
                QLineEdit:hover, QComboBox:hover {
                    border-color: #cbd5e1;
                }
            """
            button_style = """
                QPushButton {
                    padding: 10px 16px;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #6b7280, stop:1 #4b5563);
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #4b5563, stop:1 #374151);
                }
                QPushButton:pressed {
                    background: #1f2937;
                }
            """
            
            # Survey Selection (with auto-fetch and search functionality)
            # Survey Selection (with auto-fetch and search functionality)
            survey_label = QLabel("Select Survey*:")
            survey_label.setStyleSheet(label_style)
            form_fields_layout.addWidget(survey_label, row_idx, 0)

            # Create survey combo box with auto-fetch and search
            self.survey_combo = QComboBox()
            self.survey_combo.setObjectName("survey_combo")
            self.survey_combo.setStyleSheet(entry_style)
            self.survey_combo.setPlaceholderText("Loading surveys...")
            form_fields_layout.addWidget(self.survey_combo, row_idx, 1, 1, 2)  # Span 2 columns

            # Auto-load surveys when the tab is created
            QTimer.singleShot(500, self.load_surveys)  # Small delay to ensure UI is ready

            row_idx += 1
                        
            # NDD Checkboxes (only show for ris.roadathena.com and ndd.roadathena.com)
            checkbox_style = """
                QCheckBox {
                    spacing: 8px;
                    font-weight: bold;
                    color: #374151;
                    font-size: 13px;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                    border: 2px solid #cbd5e1;
                    border-radius: 4px;
                    background: white;
                }
                QCheckBox::indicator:checked {
                    background: #3b82f6;
                    border-color: #3b82f6;
                }
                QCheckBox::indicator:checked:hover {
                    background: #2563eb;
                    border-color: #2563eb;
                }
                QCheckBox:hover {
                    color: #1f2937;
                }
            """
            
            # Create NDD checkbox container
            self.ndd_checkbox_container = QWidget()
            self.ndd_checkbox_container.setObjectName("ndd_checkbox_container")
            checkbox_layout = QHBoxLayout(self.ndd_checkbox_container)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.setSpacing(15)
            
            # Create NDD checkboxes
            self.ndd_checkbox1 = QCheckBox("MCW")
            self.ndd_checkbox1.setStyleSheet(checkbox_style)
            self.ndd_checkbox1.toggled.connect(self.update_road_dropdown)
            checkbox_layout.addWidget(self.ndd_checkbox1)

            self.ndd_checkbox2 = QCheckBox("IR")
            self.ndd_checkbox2.setStyleSheet(checkbox_style)
            self.ndd_checkbox2.toggled.connect(self.update_road_dropdown)
            checkbox_layout.addWidget(self.ndd_checkbox2)

            self.ndd_checkbox3 = QCheckBox("SR")
            self.ndd_checkbox3.setStyleSheet(checkbox_style)
            self.ndd_checkbox3.toggled.connect(self.update_road_dropdown)
            checkbox_layout.addWidget(self.ndd_checkbox3)

            self.ndd_checkbox4 = QCheckBox("LR")
            self.ndd_checkbox4.setStyleSheet(checkbox_style)
            self.ndd_checkbox4.toggled.connect(self.update_road_dropdown)
            checkbox_layout.addWidget(self.ndd_checkbox4)

            self.ndd_checkbox5 = QCheckBox("T")
            self.ndd_checkbox5.setStyleSheet(checkbox_style)
            self.ndd_checkbox5.toggled.connect(self.update_road_dropdown)
            checkbox_layout.addWidget(self.ndd_checkbox5)

            self.ndd_checkbox6 = QCheckBox("FP")
            self.ndd_checkbox6.setStyleSheet(checkbox_style)
            self.ndd_checkbox6.toggled.connect(self.update_road_dropdown)
            checkbox_layout.addWidget(self.ndd_checkbox6)
            
            # Initialize current_matching_roads
            self.current_matching_roads = []
            
            checkbox_layout.addStretch()
            
            # Add to form layout but initially hide it
            form_fields_layout.addWidget(self.ndd_checkbox_container, row_idx, 0, 1, 3)
            self.ndd_checkbox_container.setVisible(False)
            
            row_idx += 1
            
            # Road Dropdown Container (initially hidden)
            self.road_dropdown_container = QWidget()
            self.road_dropdown_container.setObjectName("road_dropdown_container")
            road_dropdown_layout = QHBoxLayout(self.road_dropdown_container)
            road_dropdown_layout.setContentsMargins(0, 0, 0, 0)

            road_label = QLabel("Selected Roads:")
            road_label.setStyleSheet(label_style)
            road_dropdown_layout.addWidget(road_label)

            self.road_dropdown = QComboBox()
            self.road_dropdown.setObjectName("road_dropdown")
            self.road_dropdown.setStyleSheet(entry_style)
            self.road_dropdown.setPlaceholderText("Select roads (click button)")
            road_dropdown_layout.addWidget(self.road_dropdown)

            # Add Select Roads button
            select_roads_btn = QPushButton("Select Roads")
            select_roads_btn.setObjectName("select_roads_btn")
            select_roads_btn.setStyleSheet("""
                QPushButton {
                    padding: 6px 12px;
                    background: #3b82f6;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #2563eb;
                }
                QPushButton:pressed {
                    background: #1d4ed8;
                }
            """)
            select_roads_btn.clicked.connect(self.on_select_roads_button_clicked)
            select_roads_btn.setToolTip("Open dialog to select roads by type (MCW, SR, IR, etc.)")
            road_dropdown_layout.addWidget(select_roads_btn)

            # Add clear button
            clear_roads_btn = QPushButton("Clear Selection")
            clear_roads_btn.setObjectName("clear_roads_btn")
            clear_roads_btn.setStyleSheet("""
                QPushButton {
                    padding: 6px 12px;
                    background: #dc2626;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #b91c1c;
                }
                QPushButton:pressed {
                    background: #991b1b;
                }
            """)
            clear_roads_btn.clicked.connect(self.clear_road_selection)
            clear_roads_btn.setToolTip("Clear all road selections")
            road_dropdown_layout.addWidget(clear_roads_btn)

            road_dropdown_layout.addStretch()

            form_fields_layout.addWidget(self.road_dropdown_container, row_idx, 0, 1, 3)
            self.road_dropdown_container.setVisible(False)
            
            row_idx += 1
            
            # Folder Path
            folder_label = QLabel("Source Folder Path*:")
            folder_label.setStyleSheet(label_style)
            form_fields_layout.addWidget(folder_label, row_idx, 0)
            
            self.folder_path_input = QLineEdit()
            self.folder_path_input.setObjectName("folder_path_input")
            self.folder_path_input.setStyleSheet(entry_style)
            self.folder_path_input.setPlaceholderText("Select source folder containing raw data...")
            form_fields_layout.addWidget(self.folder_path_input, row_idx, 1)
            
            browse_btn = QPushButton("Browse")
            browse_btn.setObjectName("browse_btn")
            browse_btn.setStyleSheet(button_style)
            browse_btn.clicked.connect(self.browse_source_folder)
            form_fields_layout.addWidget(browse_btn, row_idx, 2)
            row_idx += 1
            
            # API URL Display (Read-only)
            api_label = QLabel("API Endpoint:")
            api_label.setStyleSheet(label_style)
            form_fields_layout.addWidget(api_label, row_idx, 0)

            # CHANGED: Use dash_url if available, otherwise fall back to selected_api_url
            api_url_to_display = self.dash_url if self.dash_url else self.selected_api_url
            dash_url = QLabel(api_url_to_display)
            dash_url.setStyleSheet("""
                QLabel {
                    padding: 10px 12px;
                    border: 2px solid #e1e8ed;
                    border-radius: 8px;
                    background: #f8f9fa;
                    font-size: 13px;
                    color: #495057;
                }
            """)
            dash_url.setWordWrap(True)
            form_fields_layout.addWidget(dash_url, row_idx, 1, 1, 2)
            row_idx += 1
            
            # Show/hide NDD checkboxes and road dropdown based on URL
            if api_url_to_display and any(url in api_url_to_display for url in ['ris.roadathena.com', 'ndd.roadathena.com']):
                self.ndd_checkbox_container.setVisible(True)
                self.road_dropdown_container.setVisible(True)
            
            # Model Type
            model_label = QLabel("Model Type:")
            model_label.setStyleSheet(label_style)
            form_fields_layout.addWidget(model_label, row_idx, 0)
            
            self.model_combo = QComboBox()
            self.model_combo.setObjectName("model_combo")
            self.model_combo.setStyleSheet(entry_style)
            self.model_combo.addItems(["furniture", "pavement", "vegetation"])
            form_fields_layout.addWidget(self.model_combo, row_idx, 1, 1, 2)
            row_idx += 1
            
            # Time Settings
            time_label = QLabel("Time Settings (GPX):")
            time_label.setStyleSheet(label_style)
            form_fields_layout.addWidget(time_label, row_idx, 0)
            
            self.time_combo = QComboBox()
            self.time_combo.setObjectName("time_combo")
            self.time_combo.setStyleSheet(entry_style)
            self.time_combo.addItems(["Unchanged", "Add_5_30", "Subtract_5_30"])
            form_fields_layout.addWidget(self.time_combo, row_idx, 1, 1, 2)
            row_idx += 1
            
            # Time Info
            time_info_text = (
                "Time Option Information:\n"
                "• Unchanged: GPS and video times are already in IST.\n"
                "• Add_5_30: Converts UTC GPS time to IST by adding 5h30m.\n"
                "• Subtract_5_30: Use if GPS time is 5h30m ahead of video time."
            )
            time_info_label = QLabel(time_info_text)
            time_info_label.setObjectName("time_info_label")
            time_info_label.setStyleSheet("""
                QLabel#time_info_label {
                    color: #92400e;
                    background: #fef3c7;
                    border: 2px solid #fcd34d;
                    border-radius: 8px;
                    padding: 12px;
                    font-size: 11px;
                    line-height: 1.4;
                }
            """)
            time_info_label.setWordWrap(True)
            form_fields_layout.addWidget(time_info_label, row_idx, 0, 1, 3)
            row_idx += 1
            
            # Buffer Settings Header
            buffer_header = QLabel("Buffer Settings (Video Ext.):")
            buffer_header.setStyleSheet(label_style)
            form_fields_layout.addWidget(buffer_header, row_idx, 0, 1, 3)
            row_idx += 1
            
            # Buffer Inputs
            buffer_frame = QWidget()
            buffer_frame.setObjectName("buffer_frame")
            buffer_layout = QHBoxLayout(buffer_frame)
            buffer_layout.setContentsMargins(0, 0, 0, 0)
            buffer_layout.setSpacing(0)
            
            start_label = QLabel("Start Buffer (sec):")
            start_label.setStyleSheet("font-weight: bold; color: #374151;")
            buffer_layout.addWidget(start_label)
            
            self.start_buffer_input = QLineEdit()
            self.start_buffer_input.setObjectName("start_buffer_input")
            self.start_buffer_input.setStyleSheet(entry_style)
            self.start_buffer_input.setPlaceholderText("e.g., -10")
            self.start_buffer_input.setText("-10")
            buffer_layout.addWidget(self.start_buffer_input)
            
            end_label = QLabel("End Buffer (sec):")
            end_label.setStyleSheet("font-weight: bold; color: #374151;")
            buffer_layout.addWidget(end_label)
            
            self.end_buffer_input = QLineEdit()
            self.end_buffer_input.setObjectName("end_buffer_input")
            self.end_buffer_input.setStyleSheet(entry_style)
            self.end_buffer_input.setPlaceholderText("e.g., 5")
            self.end_buffer_input.setText("0")
            buffer_layout.addWidget(self.end_buffer_input)
            
            buffer_layout.addStretch()
            form_fields_layout.addWidget(buffer_frame, row_idx, 0, 1, 3)
            row_idx += 1
            
            # Buffer Info
            buffer_info_text = (
                "Buffer Info: These values adjust the video segment extraction window derived from GPX times.\n"
                "Example: Start Buffer -10s, End Buffer 0s => Video starts 10s before GPX start and ends at GPX end."
            )
            buffer_info_label = QLabel(buffer_info_text)
            buffer_info_label.setObjectName("buffer_info_label")
            buffer_info_label.setStyleSheet("""
                QLabel#buffer_info_label {
                    color: #92400e;
                    background: #fef3c7;
                    border: 2px solid #fcd34d;
                    border-radius: 8px;
                    padding: 12px;
                    font-size: 11px;
                    line-height: 1.4;
                }
            """)
            buffer_info_label.setWordWrap(True)
            form_fields_layout.addWidget(buffer_info_label, row_idx, 0, 1, 3)
            row_idx += 1
            
            # Checkboxes
            checkbox_style = """
                QCheckBox {
                    spacing: 8px;
                    font-weight: bold;
                    color: #374151;
                    font-size: 13px;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                    border: 2px solid #cbd5e1;
                    border-radius: 4px;
                    background: white;
                }
                QCheckBox::indicator:checked {
                    background: #3b82f6;
                    border-color: #3b82f6;
                }
                QCheckBox::indicator:checked:hover {
                    background: #2563eb;
                    border-color: #2563eb;
                }
                QCheckBox:hover {
                    color: #1f2937;
                }
            """

            self.s3_checkbox = QCheckBox("Upload processed data to S3 storage")
            self.s3_checkbox.setObjectName("s3_checkbox")
            self.s3_checkbox.setStyleSheet(checkbox_style)
            self.s3_checkbox.setToolTip("Kindly check the GPX files and videos before uploading the data to S3")
            self.s3_checkbox.setToolTipDuration(5000)  # Tooltip will show for 5 seconds
            form_fields_layout.addWidget(self.s3_checkbox, row_idx, 0, 1, 3)
            row_idx += 1
            
            self.gpx_checkbox = QCheckBox("Download GPX files from Dashboard")
            self.gpx_checkbox.setObjectName("gpx_checkbox")
            self.gpx_checkbox.setStyleSheet(checkbox_style)
            self.gpx_checkbox.setChecked(True)
            form_fields_layout.addWidget(self.gpx_checkbox, row_idx, 0, 1, 3)
            row_idx += 1
            
            self.concatenate_checkbox = QCheckBox("Concatenate Videos in Folders")
            self.concatenate_checkbox.setObjectName("concatenate_checkbox")
            self.concatenate_checkbox.setStyleSheet(checkbox_style)
            self.concatenate_checkbox.setChecked(False)
            form_fields_layout.addWidget(self.concatenate_checkbox, row_idx, 0, 1, 3)
            row_idx += 1
            self.concatenate_checkbox.toggled.connect(self.on_concatenate_checkbox_toggled)

            # Progress Bar and ETA Label
            progress_container = QWidget()
            progress_container.setObjectName("progress_container")
            progress_layout = QVBoxLayout(progress_container)
            progress_layout.setContentsMargins(0, 10, 0, 10)
            progress_layout.setSpacing(5)

            progress_info_layout = QHBoxLayout()
            self.progress_label = QLabel("Ready to process")
            self.progress_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #374151;")
            self.progress_percentage_label = QLabel("0%")
            self.progress_percentage_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #3b82f6;")
            
            progress_info_layout.addWidget(self.progress_label)
            progress_info_layout.addStretch()
            progress_info_layout.addWidget(self.progress_percentage_label)
            
            progress_layout.addLayout(progress_info_layout)

            self.progress_bar = QProgressBar()
            self.progress_bar.setObjectName("progress_bar")
            self.progress_bar.setFixedHeight(12)
            self.progress_bar.setTextVisible(False)
            self.progress_bar.setStyleSheet("""
                QProgressBar {
                    border: none;
                    border-radius: 6px;
                    background: #e2e8f0;
                }
                QProgressBar::chunk {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #3b82f6, stop:1 #2563eb);
                    border-radius: 6px;
                }
            """)
            self.progress_bar.setValue(0)
            progress_layout.addWidget(self.progress_bar)

            self.eta_label = QLabel("")
            self.eta_label.setStyleSheet("font-size: 11px; color: #64748b; font-style: italic;")
            self.eta_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            progress_layout.addWidget(self.eta_label)

            form_fields_layout.addWidget(progress_container, row_idx, 0, 1, 3)
            row_idx += 1

            # Output Log Header
            log_header_frame = QWidget()
            log_header_frame.setObjectName("log_header_frame")
            log_header_layout = QHBoxLayout(log_header_frame)
            log_header_layout.setContentsMargins(0, 20, 0, 8)
            
            log_label = QLabel("Process Log")
            log_label.setObjectName("log_label")
            log_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2c3e50;")
            log_header_layout.addWidget(log_label)
            
            log_header_layout.addStretch()
            
            clear_log_btn = QPushButton("Clear Log")
            clear_log_btn.setObjectName("clear_log_btn")
            clear_log_btn.setStyleSheet(button_style)
            clear_log_btn.clicked.connect(self.clear_log)
            log_header_layout.addWidget(clear_log_btn)
            
            form_fields_layout.addWidget(log_header_frame, row_idx, 0, 1, 3)
            row_idx += 1
            
            # Output Log Text Area
            self.log_text = QTextEdit()
            self.log_text.setObjectName("log_text")
            self.log_text.setStyleSheet("""
                QTextEdit#log_text {
                    border: 2px solid #e1e8ed;
                    border-radius: 8px;
                    background: #1e293b;
                    color: #e2e8f0;
                    font-family: 'Consolas', 'Monaco', monospace;
                    font-size: 10px;
                    padding: 12px;
                    selection-background-color: #3b82f6;
                    min-height: 200px;
                }
            """)
            self.log_text.setReadOnly(True)
            
            # Add sample log content
            sample_log = """System initialized successfully...
    All dependencies loaded
    Ready for survey data processing
    Waiting for folder selection..."""
            self.log_text.setPlainText(sample_log)
            
            form_fields_layout.addWidget(self.log_text, row_idx, 0, 1, 3)
            row_idx += 1
            
            # Buttons Section
            buttons_frame = QWidget()
            buttons_frame.setObjectName("buttons_frame")
            buttons_layout = QHBoxLayout(buttons_frame)
            buttons_layout.setContentsMargins(0, 20, 0, 0)
            buttons_layout.setSpacing(15)
            
            # Left buttons
            left_buttons = QWidget()
            left_buttons.setObjectName("left_buttons")
            left_buttons_layout = QHBoxLayout(left_buttons)
            left_buttons_layout.setContentsMargins(0, 0, 0, 0)
            left_buttons_layout.setSpacing(10)
            
            help_btn = QPushButton("Help")
            help_btn.setObjectName("help_btn")
            help_btn.setStyleSheet(button_style)
            help_btn.clicked.connect(self.show_help)
            
            reset_btn = QPushButton("Reset Form")
            reset_btn.setObjectName("reset_btn")
            reset_btn.setStyleSheet(button_style)
            reset_btn.clicked.connect(self.reset_form)
            
            left_buttons_layout.addWidget(help_btn)
            left_buttons_layout.addWidget(reset_btn)
            left_buttons_layout.addStretch()
            
            # Right buttons
            right_buttons = QWidget()
            right_buttons.setObjectName("right_buttons")
            right_buttons_layout = QHBoxLayout(right_buttons)
            right_buttons_layout.setContentsMargins(0, 0, 0, 0)
            right_buttons_layout.setSpacing(10)
            
            save_btn = QPushButton("Save Draft")
            save_btn.setObjectName("save_btn")
            save_btn.setStyleSheet(button_style)
            save_btn.clicked.connect(self.save_draft)
            
            self.upload_btn = QPushButton("Upload Data")
            self.upload_btn.setObjectName("upload_btn")
            self.upload_btn.setStyleSheet("""
                QPushButton#upload_btn {
                    padding: 12px 24px;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #10b981, stop:1 #059669);
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: bold;
                    font-size: 14px;
                }
                QPushButton#upload_btn:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #059669, stop:1 #047857);
                }
                QPushButton#upload_btn:pressed {
                    background: #065f46;
                }
            """)
            self.upload_btn.clicked.connect(self.submit_form)
            
            self.cancel_btn = QPushButton("Cancel All")
            self.cancel_btn.setObjectName("cancel_btn")
            self.cancel_btn.setStyleSheet("""
                QPushButton#cancel_btn {
                    padding: 10px 20px;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #ef4444, stop:1 #dc2626);
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton#cancel_btn:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #dc2626, stop:1 #b91c1c);
                }
                QPushButton#cancel_btn:disabled {
                    background: #9ca3af;
                    color: #6b7280;
                }
            """)
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.clicked.connect(self.cancel_processing)
            
            right_buttons_layout.addWidget(save_btn)
            right_buttons_layout.addWidget(self.upload_btn)
            right_buttons_layout.addWidget(self.cancel_btn)
            
            buttons_layout.addWidget(left_buttons)
            buttons_layout.addWidget(right_buttons)
            
            form_fields_layout.addWidget(buttons_frame, row_idx, 0, 1, 3)
            row_idx += 1
            
            # Required fields note
            required_note = QLabel("* Required fields must be filled before uploading")
            required_note.setObjectName("required_note")
            required_note.setStyleSheet("""
                QLabel#required_note {
                    color: #6b7280;
                    font-size: 11px;
                    margin-top: 15px;
                    padding: 8px 12px;
                    background: #f3f4f6;
                    border: 1px solid #e5e7eb;
                    border-radius: 6px;
                }
            """)
            form_fields_layout.addWidget(required_note, row_idx, 0, 1, 3)
            
            form_layout.addWidget(form_fields)
            scroll_layout.addWidget(form_card)
            scroll_layout.addStretch()
            
            scroll_area.setWidget(scroll_content)
            content_layout.addWidget(scroll_area)
            
            main_layout.addWidget(content_widget)
            layout.addWidget(main_widget)
            
            return layout
            
        except Exception as e:
            print(f"Error in survey_data_uploader_layout: {e}")
            # Return a simple layout as fallback
            fallback_layout = QVBoxLayout()
            error_label = QLabel(f"Error creating layout: {str(e)}")
            fallback_layout.addWidget(error_label)
            return fallback_layout


    def on_concatenate_checkbox_toggled(self, checked):
        """Show warning dialog when concatenate checkbox is toggled"""
        if checked:
            # Show warning dialog
            warning_dialog = QDialog(self)
            warning_dialog.setWindowTitle("Video Concatenation Warning")
            warning_dialog.setFixedSize(500, 250)
            warning_dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint)
            
            layout = QVBoxLayout(warning_dialog)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.setSpacing(15)
            
            # Warning icon and text
            warning_widget = QWidget()
            warning_layout = QHBoxLayout(warning_widget)
            
            warning_icon = QLabel("⚠️")
            warning_icon.setStyleSheet("font-size: 48px;")
            warning_layout.addWidget(warning_icon)
            
            warning_text = QLabel(
                "<b>IMPORTANT WARNING</b><br><br>"
                "Video concatenation will merge multiple videos in each folder into a single video.<br><br>"
                "<b>⚠️ Once concatenated, videos cannot be split back into original files!</b><br><br>"
                "The concatenated video will be named using the earliest timestamp (YYYYMMDD_HHMMSS).<br>"
                "Original videos may be deleted after successful concatenation."
            )
            warning_text.setWordWrap(True)
            warning_text.setStyleSheet("font-size: 12px; line-height: 1.4;")
            warning_layout.addWidget(warning_text)
            
            layout.addWidget(warning_widget)
            
            # Checkbox for confirmation
            confirm_checkbox = QCheckBox("I understand that concatenated videos cannot be reversed")
            confirm_checkbox.setStyleSheet("font-weight: bold; color: #d32f2f;")
            layout.addWidget(confirm_checkbox)
            
            # Buttons
            button_layout = QHBoxLayout()
            
            cancel_btn = QPushButton("Cancel")
            cancel_btn.setStyleSheet("""
                QPushButton {
                    padding: 10px 20px;
                    background: #f5f5f5;
                    color: #333;
                    border: 1px solid #ddd;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #e0e0e0;
                }
            """)
            cancel_btn.clicked.connect(lambda: self.handle_concatenate_cancel(warning_dialog))
            
            confirm_btn = QPushButton("Confirm")
            confirm_btn.setStyleSheet("""
                QPushButton {
                    padding: 10px 20px;
                    background: #2196f3;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #1976d2;
                }
            """)
            confirm_btn.clicked.connect(lambda: self.handle_concatenate_confirm(warning_dialog, confirm_checkbox))
            confirm_btn.setEnabled(False)
            
            # Enable confirm button only when checkbox is checked
            confirm_checkbox.toggled.connect(confirm_btn.setEnabled)
            
            button_layout.addWidget(cancel_btn)
            button_layout.addStretch()
            button_layout.addWidget(confirm_btn)
            
            layout.addLayout(button_layout)
            
            warning_dialog.exec()

    def handle_concatenate_cancel(self, dialog):
        """Handle cancel button in concatenation warning dialog"""
        self.concatenate_checkbox.setChecked(False)
        dialog.close()

    def handle_concatenate_confirm(self, dialog, confirm_checkbox):
        """Handle confirm button in concatenation warning dialog"""
        if confirm_checkbox.isChecked():
            dialog.accept()
            self.log_message("✅ Video concatenation enabled. Videos will be merged in each folder.", "info")
        else:
            QMessageBox.warning(self, "Confirmation Required", 
                            "Please confirm that you understand videos cannot be split after concatenation.")


    # Add these methods to your class to handle the road filtering functionality:

    def get_complete_survey_data(self, survey_id):
        """Get complete survey data with roads from the correct API endpoint"""
        try:
            # Use dash_url if available, otherwise fall back to selected_api_url
            base_url = self.dash_url if self.dash_url else self.selected_api_url
            
            # Try different possible API endpoints
            endpoints = [
                f"{base_url.rstrip('/')}/api/surveys/{survey_id}/",
                f"{base_url.rstrip('/')}/api/surveys/{survey_id}",
                f"{base_url.rstrip('/')}/api/surveys/{survey_id}/roads/",
                f"{base_url.rstrip('/')}/api/surveys/{survey_id}/?include_roads=true",
            ]
            
            headers = {"Security-Password": "admin@123"}
            
            for endpoint in endpoints:
                self.log_message(f"🔍 Trying endpoint: {endpoint}", "info")
                try:
                    response = requests.get(endpoint, headers=headers, timeout=10)
                    
                    if response.status_code == 200:
                        survey_data = response.json()
                        self.log_message(f"✅ Successfully loaded survey data from: {endpoint}", "success")
                        
                        # Check if this endpoint has roads data
                        if 'roads' in survey_data and survey_data['roads']:
                            self.log_message(f"📊 Found {len(survey_data['roads'])} roads in response", "success")
                            return survey_data
                        else:
                            self.log_message("⚠️ Endpoint worked but no roads data found", "warning")
                            # Continue to next endpoint
                    else:
                        self.log_message(f"❌ Endpoint failed: {response.status_code}", "info")
                        
                except requests.exceptions.RequestException as e:
                    self.log_message(f"❌ Endpoint error: {str(e)}", "info")
                    continue
            
            # If no endpoint worked, try to get roads separately
            self.log_message("🔄 Trying to fetch roads separately...", "info")
            roads_endpoint = f"{base_url.rstrip('/')}/api/roads/?survey={survey_id}"
            try:
                response = requests.get(roads_endpoint, headers=headers, timeout=10)
                if response.status_code == 200:
                    roads_data = response.json()
                    self.log_message(f"✅ Successfully loaded {len(roads_data)} roads separately", "success")
                    
                    # Create a survey-like structure with the roads
                    survey_data = {
                        'id': survey_id,
                        'name': f"Survey {survey_id}",
                        'roads': roads_data
                    }
                    return survey_data
            except Exception as e:
                self.log_message(f"❌ Failed to load roads separately: {str(e)}", "error")
            
            self.log_message("❌ All endpoints failed to return roads data", "error")
            return None
            
        except Exception as e:
            self.log_message(f"❌ Error getting complete survey data: {str(e)}", "error")
            return None
        
    def test_survey_endpoints(self, survey_id):
        """Test all possible survey endpoints to find the correct one"""
        try:
            base_url = self.dash_url if self.dash_url else self.selected_api_url
            headers = {"Security-Password": "admin@123"}
            
            endpoints_to_test = [
                f"{base_url.rstrip('/')}/api/surveys/{survey_id}/",
                f"{base_url.rstrip('/')}/api/surveys/{survey_id}",
                f"{base_url.rstrip('/')}/api/surveys/{survey_id}/roads/",
                f"{base_url.rstrip('/')}/api/surveys/{survey_id}/?include_roads=true",
                f"{base_url.rstrip('/')}/api/surveys/{survey_id}/?expand=roads",
                f"{base_url.rstrip('/')}/api/roads/?survey={survey_id}",
            ]
            
            self.log_message("🧪 TESTING ALL ENDPOINTS:", "info")
            
            for endpoint in endpoints_to_test:
                try:
                    response = requests.get(endpoint, headers=headers, timeout=5)
                    self.log_message(f"🔍 {endpoint}", "info")
                    self.log_message(f"   Status: {response.status_code}", "info")
                    
                    if response.status_code == 200:
                        data = response.json()
                        self.log_message(f"   ✅ Success - Keys: {list(data.keys()) if isinstance(data, dict) else 'List length: ' + str(len(data))}", "success")
                        
                        # Check if it has roads data
                        if isinstance(data, dict) and 'roads' in data:
                            roads_count = len(data['roads']) if isinstance(data['roads'], list) else 'N/A'
                            self.log_message(f"   📊 Roads found: {roads_count}", "success")
                        elif isinstance(data, list):
                            self.log_message(f"   📊 This is a list of {len(data)} items", "success")
                            if data and isinstance(data[0], dict):
                                self.log_message(f"   🔍 First item keys: {list(data[0].keys())}", "info")
                    else:
                        self.log_message(f"   ❌ Failed", "error")
                        
                except Exception as e:
                    self.log_message(f"   💥 Error: {str(e)}", "error")
                    
        except Exception as e:
            self.log_message(f"❌ Endpoint testing failed: {str(e)}", "error")

    def get_current_survey_data(self, survey_id):
        """Get survey data by ID with caching and debugging"""
        try:
            # Initialize survey data cache if it doesn't exist
            if not hasattr(self, 'survey_data_cache'):
                self.survey_data_cache = {}
            
            # Check if we already have this survey data cached
            if survey_id in self.survey_data_cache:
                return self.survey_data_cache[survey_id]
            
            # Use dash_url if available, otherwise fall back to selected_api_url
            base_url = self.dash_url if self.dash_url else self.selected_api_url
            api_url = f"{base_url.rstrip('/')}/api/surveys/{survey_id}/"
            
            self.log_message(f"Fetching survey data for ID: {survey_id}", "info")
            
            # Use the same headers as other API calls
            headers = {"Security-Password": "admin@123"}
            
            response = requests.get(api_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                survey_data = response.json()
                # Cache the survey data
                self.survey_data_cache[survey_id] = survey_data
                
                # Debug: Log the structure
                if 'roads' in survey_data:
                    road_types = []
                    for road in survey_data['roads']:
                        road_type = road.get('road', {}).get('road_type', 'Unknown')
                        road_types.append(road_type)
                    
                    unique_types = list(set(road_types))
                    self.log_message(f"📊 Survey has {len(survey_data['roads'])} roads with types: {unique_types}", "info")
                
                self.log_message(f"✅ Successfully loaded survey data for ID: {survey_id}", "success")
                return survey_data
            else:
                self.log_message(f"❌ Failed to fetch survey data: {response.status_code}", "error")
                return None
                
        except requests.exceptions.ConnectionError:
            self.log_message("❌ Connection Error: Could not connect to server", "error")
            return None
        except requests.exceptions.Timeout:
            self.log_message("❌ Timeout Error: Request timed out", "error")
            return None
        except Exception as e:
            self.log_message(f"❌ Error getting survey data: {e}", "error")
            return None


    def update_road_dropdown(self):
        """Update the road dropdown with filtering support"""
        try:
            # Get selected road types from checkboxes
            selected_types = []
            checkbox_mapping = {
                self.ndd_checkbox1: "MCW",
                self.ndd_checkbox2: "IR", 
                self.ndd_checkbox3: "SR",
                self.ndd_checkbox4: "LR",
                self.ndd_checkbox5: "T",
                self.ndd_checkbox6: "FP"
            }
            
            for checkbox, road_type in checkbox_mapping.items():
                if checkbox.isChecked():
                    selected_types.append(road_type)
            
            # Clear current dropdown
            self.road_dropdown.clear()
            
            if not selected_types:
                self.road_dropdown.setPlaceholderText("Select road types first")
                return
            
            # Get current survey data
            current_survey_id = self.get_selected_survey_id()
            if not current_survey_id:
                self.road_dropdown.setPlaceholderText("No survey selected")
                return
            
            # Fetch survey data
            survey_data = self.get_complete_survey_data(current_survey_id)
            
            if not survey_data or 'roads' not in survey_data:
                self.road_dropdown.setPlaceholderText("Failed to load survey data")
                return
            
            # Find roads that match the selected types
            matching_roads = []
            roads_data = survey_data['roads']
            
            # Debug: Print first road to understand structure
            if roads_data:
                first_road = roads_data[0]
                self.log_message(f"📋 First road structure: {first_road}", "debug")
                print(f"DEBUG: First road = {first_road}")  # Also print to console
            
            for road in roads_data:
                road_id = road.get('id')
                
                # Handle both nested and flat road structures (compatibility with different APIs)
                # First try nested structure (standard roadathena API)
                road_obj = road.get('road', {})
                if isinstance(road_obj, dict) and road_obj:
                    road_name = road_obj.get('name') or road_obj.get('road_name') or road.get('name', 'Unknown')
                    road_type = road_obj.get('road_type') or road_obj.get('type') or road.get('road_type', 'Unknown')
                else:
                    # Fallback: try direct fields on road object (NHAI/NDD API format)
                    road_name = road.get('name') or road.get('road_name', 'Unknown')
                    road_type = road.get('road_type') or road.get('type', 'Unknown')
                
                # Debug: log what we extracted
                if road_id in [r['id'] for r in roads_data[:2]]:  # Log first 2 roads
                    print(f"DEBUG: Road {road_id}: name={road_name}, type={road_type}")
                
                # Check if road type starts with any selected type
                if road_type and road_type != "Unknown":
                    for selected_type in selected_types:
                        if road_type.upper().startswith(selected_type.upper()):
                            matching_roads.append({
                                'id': road_id,
                                'name': road_name,
                                'type': road_type
                            })
                            break
            
            if matching_roads:
                # Cache the matching roads for the button click
                self.current_matching_roads = matching_roads
                # Update UI to show available roads
                self.road_dropdown.setPlaceholderText(f"Ready to select from {len(matching_roads)} roads")
                self.road_dropdown.clear()
                self.road_dropdown.addItem(f"Select from {len(matching_roads)} roads")
                
                self.log_message(f"✅ Found {len(matching_roads)} matching roads - click 'Select Roads' button to choose", "success")
            else:
                # Debug: Log why no roads were found
                if roads_data:
                    self.log_message(f"⚠️ Checked {len(roads_data)} roads but none matched types: {selected_types}", "warning")
                    # Show sample road structure for debugging API issues
                    if roads_data and len(roads_data) > 0:
                        sample = roads_data[0]
                        self.log_message(f"📋 Sample road structure: {str(sample)[:150]}...", "info")
                self.road_dropdown.setPlaceholderText("No roads found for selected types")
                self.log_message("❌ No roads found for the selected types", "warning")
                    
        except Exception as e:
            self.log_message(f"Error updating road dropdown: {str(e)}", "error")

    def on_select_roads_button_clicked(self):
        """Handle Select Roads button click"""
        try:
            if not hasattr(self, 'current_matching_roads') or not self.current_matching_roads:
                # First, check if any road types are selected
                selected_types = []
                checkbox_mapping = {
                    self.ndd_checkbox1: "MCW",
                    self.ndd_checkbox2: "IR", 
                    self.ndd_checkbox3: "SR",
                    self.ndd_checkbox4: "LR",
                    self.ndd_checkbox5: "T",
                    self.ndd_checkbox6: "FP"
                }
                
                for checkbox, road_type in checkbox_mapping.items():
                    if checkbox.isChecked():
                        selected_types.append(road_type)
                
                if not selected_types:
                    self.log_message("⚠️ Please select at least one road type (MCW, IR, SR, etc.) first", "warning")
                    return
                
                # If no cached roads, fetch them again
                self.update_road_dropdown()
                if not hasattr(self, 'current_matching_roads') or not self.current_matching_roads:
                    self.log_message("❌ No roads found for the selected types", "error")
                    return
            
            # Show the selection dialog
            self.show_road_selection_dialog(self.current_matching_roads)
            
        except Exception as e:
            self.log_message(f"Error opening road selection dialog: {str(e)}", "error")


    def setup_checkbox_dropdown(self, matching_roads):
        """Setup dropdown with checkboxes for multiple road selection"""
        try:
            # Clear existing dropdown
            self.road_dropdown.clear()
            
            # Initialize selected roads list if it doesn't exist
            if not hasattr(self, 'selected_road_ids'):
                self.selected_road_ids = []
            
            # Create a custom model for the dropdown
            model = QStandardItemModel()
            
            # Add "Select All" option
            select_all_item = QStandardItem("□ Select All Roads")
            select_all_item.setCheckable(True)
            select_all_item.setData("select_all", Qt.ItemDataRole.UserRole)
            select_all_item.setCheckState(Qt.CheckState.Unchecked)
            model.appendRow(select_all_item)
            
            # Add separator
            separator_item = QStandardItem("─" * 50)
            separator_item.setEnabled(False)
            separator_item.setSelectable(False)
            model.appendRow(separator_item)
            
            # Add roads with checkboxes
            for road in matching_roads:
                road_id = road['id']
                road_name = road['name']
                road_type = road['type']
                
                item = QStandardItem(f"□ {road_name} ({road_type})")
                item.setCheckable(True)
                item.setData(road_id, Qt.ItemDataRole.UserRole)
                item.setData(road_name, Qt.ItemDataRole.UserRole + 1)
                item.setData(road_type, Qt.ItemDataRole.UserRole + 2)
                
                # Check if this road was previously selected
                if road_id in self.selected_road_ids:
                    item.setCheckState(Qt.CheckState.Checked)
                    item.setText(f"✅ {road_name} ({road_type})")
                else:
                    item.setCheckState(Qt.CheckState.Unchecked)
                
                model.appendRow(item)
            
            # Set the model to dropdown
            self.road_dropdown.setModel(model)
            
            # Connect checkbox changes
            model.itemChanged.connect(self.on_road_checkbox_changed)
            
            # Update dropdown display
            self.update_dropdown_display()
            
        except Exception as e:
            self.log_message(f"Error setting up checkbox dropdown: {str(e)}", "error")

    def show_road_selection_dialog(self, matching_roads):
        """Show a custom dialog for road selection"""
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("Select Roads")
            dialog.setMinimumSize(500, 400)
            
            layout = QVBoxLayout(dialog)
            
            # Title
            title_label = QLabel("Select roads to process:")
            title_label.setStyleSheet("font-weight: bold; font-size: 14px; margin-bottom: 10px;")
            layout.addWidget(title_label)
            
            # Scroll area for roads list
            scroll_area = QScrollArea()
            scroll_widget = QWidget()
            scroll_layout = QVBoxLayout(scroll_widget)
            
            # Initialize selected roads list
            if not hasattr(self, 'selected_road_ids'):
                self.selected_road_ids = []
            
            self.road_checkboxes = {}
            
            # Select All checkbox
            select_all_cb = QCheckBox("Select All Roads")
            select_all_cb.setStyleSheet("font-weight: bold; margin-bottom: 10px;")
            scroll_layout.addWidget(select_all_cb)
            
            # Add roads checkboxes
            for road in matching_roads:
                road_id = road['id']
                road_name = road['name']
                road_type = road['type']
                
                cb = QCheckBox(f"{road_name} ({road_type})")
                cb.road_id = road_id
                cb.road_name = road_name
                
                # Set checked state if previously selected
                if road_id in self.selected_road_ids:
                    cb.setChecked(True)
                
                self.road_checkboxes[road_id] = cb
                scroll_layout.addWidget(cb)
            
            scroll_layout.addStretch()
            scroll_area.setWidget(scroll_widget)
            scroll_area.setWidgetResizable(True)
            layout.addWidget(scroll_area)
            
            # Connect select all
            def toggle_all(checked):
                for cb in self.road_checkboxes.values():
                    cb.setChecked(checked)
            select_all_cb.toggled.connect(toggle_all)
            
            # Buttons
            button_layout = QHBoxLayout()
            ok_btn = QPushButton("OK")
            cancel_btn = QPushButton("Cancel")
            clear_btn = QPushButton("Clear All")
            
            ok_btn.clicked.connect(dialog.accept)
            cancel_btn.clicked.connect(dialog.reject)
            clear_btn.clicked.connect(lambda: toggle_all(False))
            
            button_layout.addWidget(clear_btn)
            button_layout.addStretch()
            button_layout.addWidget(cancel_btn)
            button_layout.addWidget(ok_btn)
            layout.addLayout(button_layout)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Update selected roads list
                self.selected_road_ids.clear()
                for road_id, cb in self.road_checkboxes.items():
                    if cb.isChecked():
                        self.selected_road_ids.append(road_id)
                
                self.update_dropdown_display()
                self.log_message(f"✅ Selected {len(self.selected_road_ids)} roads", "success")
            
        except Exception as e:
            self.log_message(f"Error in road selection dialog: {str(e)}", "error")

    

    def on_road_checkbox_changed(self, item):
        """Handle checkbox state changes in the road dropdown"""
        try:
            item_data = item.data(Qt.ItemDataRole.UserRole)
            item_text = item.text()
            
            # Handle "Select All" option
            if item_data == "select_all":
                if item.checkState() == Qt.CheckState.Checked:
                    # Check all roads
                    self.select_all_roads(True)
                else:
                    # Uncheck all roads
                    self.select_all_roads(False)
                return
            
            # Handle individual road selection
            road_id = item_data
            road_name = item.data(Qt.ItemDataRole.UserRole + 1)
            road_type = item.data(Qt.ItemDataRole.UserRole + 2)
            
            if item.checkState() == Qt.CheckState.Checked:
                # Add to selected list
                if road_id not in self.selected_road_ids:
                    self.selected_road_ids.append(road_id)
                    # Update item text to show checked state
                    item.setText(f"✅ {road_name} ({road_type})")
                    self.log_message(f"➕ Added road: {road_name} ({road_type})", "success")
            else:
                # Remove from selected list
                if road_id in self.selected_road_ids:
                    self.selected_road_ids.remove(road_id)
                    # Update item text to show unchecked state
                    item.setText(f"□ {road_name} ({road_type})")
                    self.log_message(f"➖ Removed road: {road_name} ({road_type})", "info")
            
            # Update the dropdown display text to show selection count
            self.update_dropdown_display()
            
            # Log current selection
            self.log_message(f"📋 Currently selected: {len(self.selected_road_ids)} roads", "info")
            
        except Exception as e:
            self.log_message(f"Error handling checkbox change: {str(e)}", "error")


    def select_all_roads(self, select):
        """Select or deselect all roads"""
        try:
            model = self.road_dropdown.model()
            
            for i in range(model.rowCount()):
                item = model.item(i)
                item_data = item.data(Qt.ItemDataRole.UserRole)
                
                # Skip non-road items (select_all and separator)
                if item_data == "select_all" or not item_data:
                    continue
                
                road_id = item_data
                road_name = item.data(Qt.ItemDataRole.UserRole + 1)
                road_type = item.data(Qt.ItemDataRole.UserRole + 2)
                
                if select:
                    item.setCheckState(Qt.CheckState.Checked)
                    if road_id not in self.selected_road_ids:
                        self.selected_road_ids.append(road_id)
                    item.setText(f"✅ {road_name} ({road_type})")
                else:
                    item.setCheckState(Qt.CheckState.Unchecked)
                    if road_id in self.selected_road_ids:
                        self.selected_road_ids.remove(road_id)
                    item.setText(f"□ {road_name} ({road_type})")
            
            # Update select all checkbox state
            for i in range(model.rowCount()):
                item = model.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == "select_all":
                    item.setCheckState(Qt.CheckState.Checked if select else Qt.CheckState.Unchecked)
                    item.setText("✅ Select All Roads" if select else "□ Select All Roads")
                    break
            
            self.update_dropdown_display()
            action = "selected" if select else "deselected"
            self.log_message(f"📋 All roads {action}. Total: {len(self.selected_road_ids)} roads", "info")
            
        except Exception as e:
            self.log_message(f"Error selecting all roads: {str(e)}", "error")

    def get_final_road_list(self):
        """Get the final list of selected road IDs"""
        try:
            # Ensure selected_road_ids exists and return it
            if not hasattr(self, 'selected_road_ids'):
                self.selected_road_ids = []
            return self.selected_road_ids.copy()
            
        except Exception as e:
            self.log_message(f"Error getting final road list: {str(e)}", "error")
            return []


    def update_dropdown_display(self):
        """Update the dropdown display text to show selection count"""
        try:
            if hasattr(self, 'selected_road_ids') and self.selected_road_ids:
                selected_count = len(self.selected_road_ids)
                # Update the dropdown text
                self.road_dropdown.clear()
                self.road_dropdown.addItem(f"Selected {selected_count} roads")
                
                # Show selected roads in log for debugging
                if selected_count <= 10:  # Only show if not too many
                    selected_names = []
                    # Get road names from the checkboxes if available
                    if hasattr(self, 'road_checkboxes'):
                        for road_id in self.selected_road_ids:
                            if road_id in self.road_checkboxes:
                                selected_names.append(self.road_checkboxes[road_id].road_name)
                    
                    if selected_names:
                        self.log_message(f"📋 Selected roads: {', '.join(selected_names)}", "info")
                else:
                    self.log_message(f"📋 Selected {selected_count} roads", "info")
            else:
                self.road_dropdown.clear()
                self.road_dropdown.setPlaceholderText("Click to select roads")
                self.road_dropdown.addItem("Click to select roads")
                
        except Exception as e:
            print(f"Error updating dropdown display: {e}")

    

 
    def get_selected_roads_info(self):
        """Get information about currently selected roads"""
        try:
            if not hasattr(self, 'selected_road_ids') or not self.selected_road_ids:
                return []
            
            selected_roads_info = []
            model = self.road_dropdown.model()
            
            for i in range(model.rowCount()):
                item = model.item(i)
                road_id = item.data(Qt.ItemDataRole.UserRole)
                
                if road_id and road_id in self.selected_road_ids:
                    road_info = {
                        'id': road_id,
                        'name': item.data(Qt.ItemDataRole.UserRole + 1),
                        'type': item.data(Qt.ItemDataRole.UserRole + 2)
                    }
                    selected_roads_info.append(road_info)
            
            return selected_roads_info
            
        except Exception as e:
            self.log_message(f"Error getting selected roads info: {str(e)}", "error")
            return []

    def clear_road_selection(self):
        """Clear all road selections"""
        try:
            if hasattr(self, 'selected_road_ids'):
                self.selected_road_ids.clear()
            
            model = self.road_dropdown.model()
            if model:
                for i in range(model.rowCount()):
                    item = model.item(i)
                    if item.isCheckable():
                        item.setCheckState(Qt.CheckState.Unchecked)
                        # Reset text to unchecked state
                        item_data = item.data(Qt.ItemDataRole.UserRole)
                        if item_data and item_data != "select_all":
                            road_name = item.data(Qt.ItemDataRole.UserRole + 1)
                            road_type = item.data(Qt.ItemDataRole.UserRole + 2)
                            item.setText(f"□ {road_name} ({road_type})")
                        elif item_data == "select_all":
                            item.setText("□ Select All Roads")
            
            self.update_dropdown_display()
            self.log_message("🗑️ Cleared all road selections", "info")
            
        except Exception as e:
            self.log_message(f"Error clearing road selection: {str(e)}", "error")

    def load_surveys(self):
        """Load surveys from API and populate the dropdown with name->id mapping - Auto-fetch version"""
        try:
            # Ensure surveys_dict is initialized
            if not hasattr(self, 'surveys_dict'):
                self.surveys_dict = {}
                
            # Initialize survey data cache
            if not hasattr(self, 'survey_data_cache'):
                self.survey_data_cache = {}
                
            # Use dash_url if available, otherwise fall back to selected_api_url
            base_url = self.dash_url if self.dash_url else self.selected_api_url
            api_url = f"{base_url.rstrip('/')}/api/surveys/"
            
            self.log_message(f"Auto-loading surveys from: {api_url}", "info")
            
            # Use the same headers as other API calls
            headers = {"Security-Password": "admin@123"}
            
            response = requests.get(api_url, headers=headers, timeout=10)
            
            self.log_message(f"API Response Status: {response.status_code}", "info")
            
            if response.status_code == 200:
                surveys_data = response.json()
                
                # Clear existing items
                self.survey_combo.clear()
                self.surveys_dict.clear()
                
                # Check if surveys_data is a list
                if isinstance(surveys_data, list):
                    # Create a list to sort surveys by name
                    surveys_list = []
                    
                    for survey in surveys_data:
                        survey_id = survey.get("id")
                        survey_name = survey.get("name", "Unnamed Survey")
                        
                        # Store in dictionary: name -> id
                        self.surveys_dict[survey_name] = survey_id
                        
                        # Cache the survey data for road filtering
                        self.survey_data_cache[survey_id] = survey
                        
                        # Add to list for sorting
                        surveys_list.append((survey_name, survey_id))
                    
                    # Sort surveys alphabetically by name (case-insensitive)
                    surveys_list.sort(key=lambda x: x[0].lower())
                    
                    # Add sorted surveys to combo box
                    for survey_name, survey_id in surveys_list:
                        self.survey_combo.addItem(survey_name)
                    
                    if self.surveys_dict:
                        self.survey_combo.setPlaceholderText("Select a survey...")
                        self.log_message(f"✅ Successfully loaded {len(self.surveys_dict)} surveys (sorted alphabetically)", "success")
                        
                        # Setup search functionality after loading data
                        self.setup_survey_search()
                    else:
                        self.survey_combo.setPlaceholderText("No surveys available")
                        self.log_message("⚠️ No surveys found in the response", "warning")
                else:
                    self.log_message(f"❌ Unexpected response format: {type(surveys_data)}", "error")
                    self.survey_combo.setPlaceholderText("Invalid response format")
                    
            else:
                error_msg = f"Failed to load surveys: {response.status_code}"
                try:
                    error_detail = response.json()
                    error_msg += f" - {error_detail}"
                except:
                    error_msg += f" - {response.text}"
                
                self.log_message(f"❌ {error_msg}", "error")
                self.survey_combo.setPlaceholderText("Failed to load surveys")
                    
        except requests.exceptions.ConnectionError:
            self.log_message("❌ Connection Error: Could not connect to server", "error")
            self.survey_combo.setPlaceholderText("Connection failed")
        except requests.exceptions.Timeout:
            self.log_message("❌ Timeout Error: Request timed out", "error")
            self.survey_combo.setPlaceholderText("Request timeout")
        except Exception as e:
            self.log_message(f"❌ Error loading surveys: {str(e)}", "error")
            self.survey_combo.setPlaceholderText("Error loading surveys")

    def dump_survey_data(self, survey_id):
        """Dump complete survey data for debugging"""
        try:
            base_url = self.dash_url if self.dash_url else self.selected_api_url
            api_url = f"{base_url.rstrip('/')}/api/surveys/{survey_id}/"
            
            headers = {"Security-Password": "admin@123"}
            response = requests.get(api_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                survey_data = response.json()
                
                # Save to file for detailed inspection
                import json
                filename = f"survey_{survey_id}_debug.json"
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(survey_data, f, indent=2, ensure_ascii=False)
                
                self.log_message(f"💾 Complete survey data saved to: {filename}", "success")
                
                # Also log first road structure
                if 'roads' in survey_data and survey_data['roads']:
                    first_road = survey_data['roads'][0]
                    self.log_message("🔍 FIRST ROAD STRUCTURE:", "info")
                    self.log_message(f"{json.dumps(first_road, indent=2, ensure_ascii=False)}", "info")
                else:
                    self.log_message("❌ No roads found in survey data", "error")
                    
            else:
                self.log_message(f"❌ Failed to fetch survey data: {response.status_code}", "error")
                
        except Exception as e:
            self.log_message(f"❌ Dump error: {str(e)}", "error")


    def debug_survey_structure(self, survey_id):
        """Debug method to understand the survey data structure"""
        try:
            base_url = self.dash_url if self.dash_url else self.selected_api_url
            api_url = f"{base_url.rstrip('/')}/api/surveys/{survey_id}/"
            
            headers = {"Security-Password": "admin@123"}
            response = requests.get(api_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                survey_data = response.json()
                self.log_message("🔍 SURVEY DATA STRUCTURE:", "info")
                self.log_message(f"Survey ID: {survey_data.get('id')}", "info")
                self.log_message(f"Survey Name: {survey_data.get('name')}", "info")
                
                if 'roads' in survey_data:
                    self.log_message(f"Number of roads: {len(survey_data['roads'])}", "info")
                    for i, road in enumerate(survey_data['roads'][:5]):  # Show first 5 roads
                        self.log_message(f"Road {i+1}:", "info")
                        self.log_message(f"  - ID: {road.get('id')}", "info")
                        self.log_message(f"  - Road Name: {road.get('road', {}).get('name')}", "info")
                        self.log_message(f"  - Road Type: {road.get('road', {}).get('road_type')}", "info")
                        self.log_message(f"  - Full road data: {road.get('road', {})}", "info")
                else:
                    self.log_message("No 'roads' key in survey data", "warning")
                    
            else:
                self.log_message(f"Failed to fetch survey data: {response.status_code}", "error")
                
        except Exception as e:
            self.log_message(f"Debug error: {str(e)}", "error")

    
    def get_selected_survey_id(self):
        """Get the selected survey ID from the dropdown"""
        selected_name = self.survey_combo.currentText().strip()
        
        # Return the ID from dictionary
        return self.surveys_dict.get(selected_name)


    
    def setup_survey_search(self):
        """Setup search functionality for survey dropdown"""
        try:
            # Make sure surveys_dict exists
            if not hasattr(self, 'surveys_dict') or not self.surveys_dict:
                self.log_message("⚠️ No surveys available for search setup", "warning")
                return
                
            # Make the combo box editable for search
            self.survey_combo.setEditable(True)
            self.survey_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            
            # Create a completer for search suggestions
            self.survey_completer = QCompleter(list(self.surveys_dict.keys()))
            self.survey_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self.survey_completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self.survey_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            
            self.survey_combo.setCompleter(self.survey_completer)
            
            # Style the combo box for better appearance
            self.survey_combo.setStyleSheet("""
                QComboBox {
                    padding: 10px 12px;
                    border: 2px solid #e1e8ed;
                    border-radius: 8px;
                    background: white;
                    font-size: 13px;
                    selection-background-color: #3b82f6;
                }
                QComboBox:focus {
                    border-color: #3b82f6;
                    background: #f8fafc;
                }
                QComboBox:hover {
                    border-color: #cbd5e1;
                }
                QComboBox QAbstractItemView {
                    border: 2px solid #e1e8ed;
                    border-radius: 8px;
                    background: white;
                    selection-background-color: #3b82f6;
                    selection-color: white;
                    outline: none;
                }
            """)
            
        except Exception as e:
            self.log_message(f"❌ Error setting up survey search: {str(e)}", "error")

    def validate_survey_selection(self):
        """Validate that a survey is selected and available"""
        if not hasattr(self, 'surveys_dict') or not self.surveys_dict:
            return False, "No surveys available. Please check your connection and try refreshing."
        
        selected_name = self.survey_combo.currentText().strip()
        if not selected_name or selected_name == "Loading surveys..." or selected_name == "Select a survey...":
            return False, "Please select a survey from the dropdown."
        
        survey_id = self.get_selected_survey_id()
        if survey_id is None:
            return False, "Invalid survey selection. Please select a valid survey from the dropdown."
        
        return True, "Valid"
        
    def add_survey_refresh_button(self):
        """Add a refresh button to reload surveys"""
        # Find the parent layout of the survey combo
        parent_widget = self.survey_combo.parent()
        if parent_widget and hasattr(parent_widget, 'layout'):
            layout = parent_widget.layout()
            if layout:
                # Get the position of survey_combo in the layout
                for i in range(layout.count()):
                    item = layout.itemAt(i)
                    if item and item.widget() == self.survey_combo:
                        # Create a horizontal layout to hold combo and refresh button
                        h_layout = QHBoxLayout()
                        h_layout.setContentsMargins(0, 0, 0, 0)
                        h_layout.setSpacing(5)
                        
                        # Remove the combo from its current position
                        layout.removeWidget(self.survey_combo)
                        
                        # Add combo to new layout
                        h_layout.addWidget(self.survey_combo)
                        
                        # Add refresh button
                        refresh_btn = QPushButton("🔄")
                        refresh_btn.setObjectName("survey_refresh_btn")
                        refresh_btn.setToolTip("Reload surveys")
                        refresh_btn.setStyleSheet("""
                            QPushButton#survey_refresh_btn {
                                padding: 8px;
                                background: #f8f9fa;
                                border: 2px solid #e1e8ed;
                                border-radius: 6px;
                                font-size: 12px;
                                min-width: 30px;
                                max-width: 30px;
                            }
                            QPushButton#survey_refresh_btn:hover {
                                background: #e9ecef;
                                border-color: #cbd5e1;
                            }
                            QPushButton#survey_refresh_btn:pressed {
                                background: #dee2e6;
                            }
                        """)
                        refresh_btn.clicked.connect(self.refresh_surveys)
                        
                        h_layout.addWidget(refresh_btn)
                        
                        # Add the new layout to the original position
                        layout.insertLayout(i, h_layout)
                        break

    def refresh_surveys(self):
        """Reload surveys from API"""
        self.log_message("🔄 Reloading surveys...", "info")
        self.survey_combo.setPlaceholderText("Reloading...")
        QTimer.singleShot(100, self.load_surveys)

    def clear_survey_cache(self):
        """Clear the survey data cache"""
        if hasattr(self, 'survey_data_cache'):
            self.survey_data_cache.clear()
        self.log_message("Survey cache cleared", "info")
    
    def get_selected_survey_id(self):
        """Get the selected survey ID from the survey dropdown"""
        try:
            # Get the survey tab
            survey_tab = self.tabs.widget(1)  # Survey Data Uploader is at index 1
            survey_combo = survey_tab.findChild(QComboBox, "survey_combo")
            
            if not survey_combo:
                return None
                
            selected_text = survey_combo.currentText().strip()
            
            # If we have a surveys_dict, use it
            if hasattr(self, 'surveys_dict') and selected_text in self.surveys_dict:
                return self.surveys_dict[selected_text]
            
            # Try regex extraction as fallback
            import re
            survey_id_match = re.search(r'\(ID:\s*(\d+)\)', selected_text)
            if survey_id_match:
                return survey_id_match.group(1)
                
            # Try to extract any number from the text
            numbers = re.findall(r'\d+', selected_text)
            if numbers:
                return numbers[0]
                
            return None
            
        except Exception as e:
            print(f"Error getting survey ID: {e}")
            return None
    
    
    
    def submit_form(self):
        """Modified submit form to use survey dropdown with validation and road filtering"""
        try:
            # Validate survey selection
            selected_name = self.survey_combo.currentText().strip()
            if not selected_name or selected_name == "Loading surveys..." or selected_name == "Select a survey...":
                QMessageBox.critical(self, "Input Error", "Please select a survey from the dropdown.")
                return
            
            # Get survey ID from dictionary
            survey_id = self.get_selected_survey_id()
            if survey_id is None:
                QMessageBox.critical(self, "Input Error", "Invalid survey selection. Please select a valid survey.")
                return
                
            folder_path = self.folder_path_input.text().strip()
            
            if not folder_path or not Path(folder_path).is_dir():
                QMessageBox.critical(self, "Input Error", "Please select a valid source folder.")
                return
            
            # Get the final road list
            selected_roads = self.get_final_road_list()
            
            # Log the selected roads
            if selected_roads:
                self.log_message(f"🛣️ Processing {len(selected_roads)} selected roads: {selected_roads}", "info")
            else:
                self.log_message("🛣️ No roads selected - will process all roads in survey", "warning")
            
            # Get time settings from the form
            time_option = self.time_combo.currentText()
            start_buffer = self.start_buffer_input.text()
            end_buffer = self.end_buffer_input.text()
            
            # Store time settings for HTML logging
            self.current_time_settings = {
                'time_option': time_option,
                'start_buffer': start_buffer,
                'end_buffer': end_buffer
            }
            
            # Use dash_url if available, otherwise fall back to selected_api_url
            api_url_to_use = self.dash_url if self.dash_url else self.selected_api_url
            
            # Log the settings
            self.log_message(f"🚀 Starting process for Survey: {selected_name}", "info")
            self.log_message(f"📋 Survey ID: {survey_id}", "info")
            self.log_message(f"📁 Source Folder: {folder_path}", "info")
            self.log_message(f"🌐 API URL: {api_url_to_use}", "info")
            self.log_message(f"🤖 Model Type: {self.model_combo.currentText()}", "info")
            self.log_message(f"⏰ Time Setting: {time_option}", "info")
            self.log_message(f"⏪ Start Buffer: {start_buffer} seconds", "info")
            self.log_message(f"⏩ End Buffer: {end_buffer} seconds", "info")
            self.log_message(f"☁️ Upload to S3: {'Yes' if self.s3_checkbox.isChecked() else 'No'}", "info")
            self.log_message(f"🗺️ Download GPX: {'Yes' if self.gpx_checkbox.isChecked() else 'No'}", "info")
            self.log_message("=" * 60, "info")
            
            self.upload_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.is_processing_active = True
            self.current_phase = "ORGANIZATION"  # Reset phase
            
            # Reset progress bar and label
            self.progress_bar.setValue(0)
            self.progress_percentage_label.setText("0%")
            self.progress_label.setText("Initializing...")
            self.eta_label.setText("")
            self.processing_start_time = time.time()
            
            # Start processing thread - pass the survey ID (integer) and selected roads
            self.processing_thread = ProcessingThread(
                self, survey_id, folder_path, api_url_to_use,
                self.model_combo.currentText(), time_option,
                start_buffer, end_buffer,
                self.s3_checkbox.isChecked(), self.gpx_checkbox.isChecked()
            )
            
            # Store the selected roads for the processing thread to access
            self.selected_road_ids = selected_roads
            
            if hasattr(self.processing_thread, 'selected_roads'):
                self.processing_thread.selected_roads = selected_roads
            
            self.processing_thread.log_signal.connect(self.log_message)
            self.processing_thread.progress_signal.connect(self.update_progress)
            self.processing_thread.finished_signal.connect(self.processing_finished)
            self.processing_thread.start()
            
        except Exception as e:
            self.log_message(f"❌ Error in submit_form: {str(e)}", "error")
            QMessageBox.critical(self, "Submission Error", f"Failed to submit form: {str(e)}")
            self.upload_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)


    def browse_source_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Source Folder")
        if folder:
            # Debug SSD path
            print(f"📂 Folder selected via QFileDialog: {folder}")
            path_obj = Path(folder)
            print(f"🔍 Path exists: {path_obj.exists()}")
            print(f"🔍 Is directory: {path_obj.is_dir()}")
            print(f"🔍 Absolute path: {path_obj.absolute()}")
            
            self.folder_path_input.setText(folder)
            self.log_message(f"Selected source folder: {folder}", "info")
    
    def clear_log(self):
        self.log_text.clear()
    
    def log_message(self, message, level="info"):
        timestamp = QDateTime.currentDateTime().toString("[hh:mm:ss] ")
        
        # Add icons based on level if not present
        msg_icon = ""
        if level == "error" and "❌" not in message: msg_icon = "❌ "
        elif level == "success" and "✅" not in message: msg_icon = "✅ "
        elif level == "warning" and "⚠️" not in message: msg_icon = "⚠️ "
        elif level == "info" and not any(ic in message for ic in ["⚙️", "📋", "📁", "🌐", "⏰", "⏪", "⏩", "☁️", "🗺️", "🚀", "🏁", "📝", "🗑️", "🔗"]): 
            msg_icon = "🔹 "

        formatted_message = f"{timestamp} {msg_icon}{message}"
        
        # Color coding with richer colors
        if level == "error":
            formatted_message = f'<span style="color: #ef4444; font-weight: bold;">{formatted_message}</span>'
        elif level == "success":
            formatted_message = f'<span style="color: #10b981; font-weight: bold;">{formatted_message}</span>'
        elif level == "warning":
            formatted_message = f'<span style="color: #f59e0b;">{formatted_message}</span>'
        elif level == "info":
            formatted_message = f'<span style="color: #3b82f6;">{formatted_message}</span>'
        
        self.log_text.append(formatted_message)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
    
    def show_help(self):
        help_text = """
        <h3>How to Use the Upload Form</h3>
        <p><b>Step 1: Enter a Survey ID</b><br>
        This is a unique identifier for your survey data upload.</p>
        
        <p><b>Step 2: Select Folder Path</b><br>
        Click "Browse" to select the folder containing your raw video files.</p>
        
        <p><b>Step 3: Configure Options</b><br>
        - API Endpoint: Selected at login and cannot be changed.<br>
        - Model Type: Choose the model relevant to your survey.<br>
        - Time Settings: Adjust GPS time if it's not in IST.<br>
        - Buffer Settings: Fine-tune start/end time buffers.<br>
        - Upload to S3: Check this to upload processed videos to AWS S3.</p>
        
        <p><b>Step 4: Upload Data</b><br>
        Click "Upload Data" to begin processing.</p>
        """
        
        QMessageBox.information(self, "Help", help_text)
    
    def reset_form(self):
        self.survey_combo.setCurrentIndex(0)
        # self.folder_path_input.clear()
        self.model_combo.setCurrentIndex(0)
        self.time_combo.setCurrentIndex(0)
        self.start_buffer_input.setText("-10")
        self.end_buffer_input.setText("0")
        self.s3_checkbox.setChecked(False)
        self.gpx_checkbox.setChecked(True)
        self.clear_log()
        self.log_message("Form reset.", "info")
    
    def save_draft(self):
        draft_data = {
            "survey_id": self.get_selected_survey_id(),
            "folder_path": self.folder_path_input.text(),
            "api_url": self.selected_api_url,  # Use the selected API URL
            "model_type": self.model_combo.currentText(),
            "time_setting": self.time_combo.currentText(),
            "start_buffer": self.start_buffer_input.text(),
            "end_buffer": self.end_buffer_input.text(),
            "upload_to_s3": self.s3_checkbox.isChecked(),
            "download_gpx": self.gpx_checkbox.isChecked()
        }
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Draft", "", "JSON Files (*.json)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    json.dump(draft_data, f, indent=4)
                self.log_message(f"Draft saved to {file_path}", "success")
            except Exception as e:
                self.log_message(f"Error saving draft: {str(e)}", "error")
    


    def on_ui_heartbeat(self):
        """Update UI elements to show the system is 'alive' during processing"""
        if not hasattr(self, 'is_processing_active') or not self.is_processing_active:
            return
            
        self.ui_tick = (self.ui_tick + 1) % 4
        dots = "." * (self.ui_tick + 1)
        
        # Make the progress label feel alive
        current_text = self.progress_label.text()
        if "..." in current_text:
            base_text = current_text.split("...")[0]
            self.progress_percentage_label.setText(f"{self.progress_bar.value()}% {'.' * (self.ui_tick + 1)}")
        
        # Subtle pulsing for ETA label
        if self.eta_label.text():
            alpha = [0.7, 1.0, 0.7, 1.0][self.ui_tick]
            self.eta_label.setStyleSheet(f"font-size: 11px; color: rgba(100, 116, 139, {alpha}); font-style: italic;")

    def update_progress(self, current, total, filename):
        """Update progress bar with multi-phase scaling and ETA"""
        self.is_processing_active = True
        
        if self.current_phase == "ORGANIZATION":
            if "Uploading" in filename or "Initializing S3" in filename or "S3" in filename:
                self.current_phase = "UPLOAD"
        elif self.current_phase == "IDLE":
            if "Organizing" in filename or "Processing video" in filename:
                self.current_phase = "ORGANIZATION"
            elif "Uploading" in filename or "Initializing S3" in filename:
                self.current_phase = "UPLOAD"

        if total > 0:
            # Phase-based percentage calculation
            # ORGANIZATION phase: 0% -> 30%
            # UPLOAD phase: 30% -> 100%
            inner_percentage = (current / total) * 100
            
            if self.current_phase == "ORGANIZATION":
                display_percentage = inner_percentage * 0.3
            elif self.current_phase == "UPLOAD":
                display_percentage = 30 + (inner_percentage * 0.7)
            else:
                display_percentage = inner_percentage

            self.progress_bar.setValue(int(display_percentage))
            self.progress_percentage_label.setText(f"{display_percentage:.1f}%")
            
            # Clean up filename for display
            display_name = filename
            if len(display_name) > 30:
                display_name = "..." + display_name[-27:]
            
            phase_text = "Step 1/2 (Preparing)" if self.current_phase == "ORGANIZATION" else "Step 2/2 (Uploading)"
            self.progress_label.setText(f"{phase_text}: {display_name}")
            
            # ETA Calculation (Overall)
            if not hasattr(self, 'processing_start_time') or self.processing_start_time is None:
                self.processing_start_time = time.time()
            
            elapsed_time = time.time() - self.processing_start_time
            if display_percentage > 0:
                total_estimated_time = (elapsed_time / display_percentage) * 100
                remaining_time = max(0, total_estimated_time - elapsed_time)
                
                if remaining_time > 0:
                    minutes, seconds = divmod(int(remaining_time), 60)
                    eta_text = f"Estimated total remaining: {minutes}m {seconds}s" if minutes > 0 else f"Estimated total remaining: {seconds}s"
                    self.eta_label.setText(eta_text)
                else:
                    self.eta_label.setText("Finalizing...")
        elif total == 0 and current == 0:
            self.progress_bar.setValue(0)
            self.progress_percentage_label.setText("0%")
            self.eta_label.setText("")
    
    def get_elapsed_time_string(self):
        """Get formatted elapsed time since processing started"""
        if hasattr(self, 'processing_start_time') and self.processing_start_time:
            elapsed = time.time() - self.processing_start_time
            minutes, seconds = divmod(int(elapsed), 60)
            if minutes > 0:
                return f"{minutes}m {seconds}s"
            return f"{seconds}s"
        return "N/A"

    def cancel_processing(self):
        if hasattr(self, 'processing_thread'):
            self.processing_thread.cancel()
        self.is_processing_active = False
        self.log_message("Cancellation requested...", "warning")
        self.cancel_btn.setEnabled(False)
        self.upload_btn.setEnabled(True)
        # self.upload_progress_bar.setVisible(False)
    
    def processing_finished(self, success, message):
        self.upload_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.is_processing_active = False # Stop heartbeat animations
        
        if success:
            self.log_message("Processing completed successfully!", "success")
            self.progress_bar.setValue(100)
            self.progress_percentage_label.setText("100%")
            self.progress_label.setText("Completed successfully")
            self.eta_label.setText("Total time: " + self.get_elapsed_time_string())
        else:
            self.log_message(f"Processing failed: {message}", "error")
            self.progress_label.setText("Processing failed")
            self.eta_label.setText("")
            # Generate HTML log even for failed processing
            if hasattr(self, 'processing_thread'):
                self.processing_thread.generate_final_html_log(False)
        
        QMessageBox.information(self, "Processing Complete", message)

    def s3_upload_finished(self, result):
        """Handle S3 upload completion"""
        success_count = result.get("success_count", 0)
        failed_count = result.get("failed_count", 0)
        html_log_path = result.get("html_log_file", "")
        
        if html_log_path:
            self.enhanced_log_message(f"S3 Upload HTML log: {html_log_path}", "info")
        
        if success_count > 0 and failed_count == 0:
            self.enhanced_log_message(f"S3 upload completed successfully! {success_count} files uploaded.", "success")
            self.enhanced_log_message("Session completed successfully", "info")
            self.generate_final_html_log(True)
            self.finished_signal.emit(True, f"Processing completed successfully! {success_count} files uploaded to S3.")
        elif success_count > 0:
            self.enhanced_log_message(f"S3 upload partially completed. {success_count} succeeded, {failed_count} failed.", "warning")
            self.enhanced_log_message("Session completed with warnings", "info")
            self.generate_final_html_log(True)
            self.finished_signal.emit(True, f"Processing completed with {success_count} S3 uploads successful and {failed_count} failed.")
        else:
            self.enhanced_log_message("S3 upload failed completely.", "error")
            self.generate_final_html_log(False)
            self.finished_signal.emit(False, "S3 upload failed completely.")



    def generate_html_log(self):
        """Generate HTML log with time settings"""
        try:
            # Get the selected survey ID and name
            survey_id = self.get_selected_survey_id()
            selected_survey_name = self.survey_combo.currentText()
            
            # Create log data with time settings
            log_data = {
                'username': self.username,
                'survey_id': survey_id,
                'survey_name': selected_survey_name,
                'start_time': datetime.now().isoformat(),
                'system_info': get_system_info(),
                'time_settings': getattr(self, 'current_time_settings', {
                    'time_option': 'Not specified',
                    'start_buffer': 'Not specified', 
                    'end_buffer': 'Not specified'
                }),
                'model_type': self.model_combo.currentText(),
                'road_ids': [],  # This will be populated by the processing thread
                'entries': self.get_log_entries()
            }
            
            # Generate HTML log
            html_log_path = HTMLLogGenerator.create_html_log(log_data)
            self.log_message(f"HTML log generated: {html_log_path}", "info")
            
        except Exception as e:
            self.log_message(f"Error generating HTML log: {str(e)}", "error")

    def get_log_entries(self):
        """Extract log entries from the log text widget"""
        log_entries = []
        log_content = self.log_text.toPlainText()
        
        for line in log_content.split('\n'):
            if line.strip():
                # Parse the log line to extract timestamp, level, and message
                timestamp_match = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]', line)
                
                if timestamp_match:
                    timestamp = timestamp_match.group(1)
                    # Extract the message part (remove timestamp and any HTML tags)
                    message = re.sub(r'\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]', '', line).strip()
                    message = re.sub(r'<[^>]+>', '', message)  # Remove HTML tags
                    
                    # Determine log level based on message content
                    level = "info"
                    if "ERROR" in message or "Error" in message or "FAILED" in message:
                        level = "error"
                    elif "SUCCESS" in message or "Success" in message or "completed successfully" in message:
                        level = "success"
                    elif "WARNING" in message or "Warning" in message:
                        level = "warning"
                    
                    log_entries.append({
                        "timestamp": timestamp,
                        "level": level,
                        "message": message
                    })
        
        return log_entries

# ---------------- MAIN APPLICATION ----------------
class RoadAthenaApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.login_page = None
        self.main_window = None
        self.selected_api_url = ""
        self.dash_url = ""  # Add dash_url storage

    def show_login(self):
        if self.main_window:
            self.main_window.close()
            self.main_window = None
        if self.login_page:
            self.login_page.close()
        self.login_page = LoginPage()
        self.login_page.finished.connect(self.handle_login_result)
        self.login_page.show()

    # In your login successful handler
    def handle_login_result(self, result):
        if result == QDialog.DialogCode.Accepted:
            self.selected_api_url = self.login_page.selected_api_url
            self.dash_url = self.login_page.dash_url
            self.auth_token = self.login_page.auth_token
            
            # Store login data for later use
            self.login_data = {
                'auth_token': self.login_page.auth_token,
                'user_data': self.login_page.user_data
            }
            
            username = self.login_page.username_input.text()
            
            self.show_main_app(username)
        else:
            self.quit()

    def show_main_app(self, username):
        # Ensure we have the auth token from login
        auth_token = getattr(self.login_page, 'auth_token', '')
        user_data = getattr(self.login_page, 'user_data', {})
        
        # Pass all login data to the main window
        self.main_window = RoadAthenaUI(
            username, 
            self.selected_api_url, 
            self.dash_url, 
            {
                'auth_token': auth_token,
                'user_data': user_data
            }
        )
        self.main_window.show()


# ---------------- MAIN ----------------
if __name__ == "__main__":
    app = RoadAthenaApp(sys.argv)
    app.show_login()
    sys.exit(app.exec())
