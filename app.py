from flask import Flask, request, jsonify, render_template, send_file, Response
import yt_dlp
import os
import re
import json
import tempfile
import threading
import time
import shutil
from urllib.parse import urlparse, unquote
from datetime import datetime

app = Flask(__name__, template_folder='.', static_folder='.')

# Configuration
DOWNLOAD_FOLDER = os.path.join(tempfile.gettempdir(), 'jiksdrop_downloads')
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Supported platforms
SUPPORTED_PLATFORMS = [
    'youtube.com', 'youtu.be', 'youtube.com/shorts',
    'instagram.com', 'instagr.am',
    'tiktok.com', 'vm.tiktok.com',
    'facebook.com', 'fb.watch', 'fb.com',
    'twitter.com', 'x.com', 't.co',
    'pinterest.com', 'pin.it',
    'reddit.com', 'redd.it',
    'vimeo.com',
    'snapchat.com',
    'linkedin.com',
    'twitch.tv',
    'dailymotion.com', 'dai.ly'
]

def is_valid_url(url):
    """Check if URL is valid and from supported platform"""
    try:
        result = urlparse(url)
        if not all([result.scheme, result.netloc]):
            return False
        domain = result.netloc.lower()
        return any(platform in domain for platform in SUPPORTED_PLATFORMS)
    except:
        return False

def detect_platform(url):
    """Detect which platform the URL belongs to"""
    url_lower = url.lower()
    platforms = {
        'youtube': ['youtube.com', 'youtu.be'],
        'instagram': ['instagram.com', 'instagr.am'],
        'tiktok': ['tiktok.com', 'vm.tiktok.com'],
        'facebook': ['facebook.com', 'fb.watch', 'fb.com'],
        'twitter': ['twitter.com', 'x.com', 't.co'],
        'pinterest': ['pinterest.com', 'pin.it'],
        'reddit': ['reddit.com', 'redd.it'],
        'vimeo': ['vimeo.com'],
        'snapchat': ['snapchat.com'],
        'linkedin': ['linkedin.com'],
        'twitch': ['twitch.tv'],
        'dailymotion': ['dailymotion.com', 'dai.ly']
    }
    for name, domains in platforms.items():
        if any(d in url_lower for d in domains):
            return name
    return 'unknown'

def get_video_info(url):
    """Get video info using yt-dlp without downloading"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'skip_download': True,
        'cookiefile': None,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # Extract video formats
            formats = []
            if 'formats' in info:
                seen_qualities = set()
                for f in info['formats']:
                    if f.get('vcodec') != 'none' and f.get('height'):
                        quality = f"{f['height']}p"
                        if quality not in seen_qualities:
                            seen_qualities.add(quality)
                            formats.append({
                                'quality': quality,
                                'format_id': f['format_id'],
                                'ext': f.get('ext', 'mp4'),
                                'filesize': f.get('filesize') or f.get('filesize_approx', 0)
                            })

                # Sort by quality (highest first)
                formats.sort(key=lambda x: int(x['quality'].replace('p', '')), reverse=True)

            return {
                'success': True,
                'title': info.get('title', 'Unknown Video'),
                'description': info.get('description', '')[:200],
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', info.get('channel', 'Unknown')),
                'thumbnail': info.get('thumbnail', ''),
                'view_count': info.get('view_count', 0),
                'platform': detect_platform(url),
                'url': url,
                'formats': formats[:10],
                'webpage_url': info.get('webpage_url', url)
            }
    except Exception as e:
        return {'success': False, 'error': str(e)}

@app.route('/')
def index():
    return app.send_static_file('jiksdrop.html')

@app.route('/api/info', methods=['POST'])
def get_info():
    """Get video information"""
    data = request.get_json()
    url = data.get('url', '').strip()

    if not url:
        return jsonify({'success': False, 'error': 'No URL provided'}), 400

    if not is_valid_url(url):
        return jsonify({'success': False, 'error': 'Invalid or unsupported URL. Supported: YouTube, Instagram, TikTok, Facebook, Twitter, Pinterest, Reddit, Vimeo, Snapchat, LinkedIn, Twitch, Dailymotion'}), 400

    result = get_video_info(url)
    return jsonify(result)

@app.route('/api/download', methods=['POST'])
def download_video():
    """Download video/audio file and return it"""
    data = request.get_json()
    url = data.get('url', '').strip()
    quality = data.get('quality', 'best')
    format_type = data.get('type', 'video')

    if not url or not is_valid_url(url):
        return jsonify({'success': False, 'error': 'Invalid URL'}), 400

    # Generate safe filename
    timestamp = int(time.time())

    try:
        # First get title for filename
        ydl_opts_info = {'quiet': True, 'no_warnings': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)
            raw_title = info.get('title', 'video')
            safe_title = re.sub(r'[^\w\s-]', '', raw_title).strip()[:50]
            if not safe_title:
                safe_title = 'video'
    except:
        safe_title = 'video'

    try:
        if format_type == 'audio':
            output_file = os.path.join(DOWNLOAD_FOLDER, f'{safe_title}_{timestamp}.mp3')
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_FOLDER, f'{safe_title}_{timestamp}.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
                'no_warnings': True,
            }
        else:
            output_file = os.path.join(DOWNLOAD_FOLDER, f'{safe_title}_{timestamp}.mp4')

            if quality == 'best':
                format_spec = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            elif quality.endswith('p'):
                height = quality.replace('p', '')
                format_spec = f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}]'
            else:
                format_spec = 'best'

            ydl_opts = {
                'format': format_spec,
                'outtmpl': os.path.join(DOWNLOAD_FOLDER, f'{safe_title}_{timestamp}.%(ext)s'),
                'merge_output_format': 'mp4',
                'quiet': True,
                'no_warnings': True,
            }

        # Download the file
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Find the actual downloaded file
        downloaded_file = None
        base_path = os.path.join(DOWNLOAD_FOLDER, f'{safe_title}_{timestamp}')

        # Check for the expected file
        if format_type == 'audio':
            expected = base_path + '.mp3'
            if os.path.exists(expected):
                downloaded_file = expected
            else:
                # Try other audio extensions
                for ext in ['.m4a', '.webm', '.opus', '.ogg']:
                    alt = base_path + ext
                    if os.path.exists(alt):
                        downloaded_file = alt
                        break
        else:
            expected = base_path + '.mp4'
            if os.path.exists(expected):
                downloaded_file = expected
            else:
                for ext in ['.webm', '.mkv', '.m4v']:
                    alt = base_path + ext
                    if os.path.exists(alt):
                        downloaded_file = alt
                        break

        if not downloaded_file or not os.path.exists(downloaded_file):
            # Search directory for matching files
            for f in os.listdir(DOWNLOAD_FOLDER):
                if f.startswith(f'{safe_title}_{timestamp}'):
                    downloaded_file = os.path.join(DOWNLOAD_FOLDER, f)
                    break

        if not downloaded_file or not os.path.exists(downloaded_file):
            return jsonify({'success': False, 'error': 'File not found after download'}), 500

        # Determine final filename
        if format_type == 'audio':
            final_name = f'{safe_title}.mp3'
        else:
            final_name = f'{safe_title}.mp4'

        return send_file(
            downloaded_file,
            as_attachment=True,
            download_name=final_name,
            mimetype='video/mp4' if format_type == 'video' else 'audio/mpeg'
        )

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Cleanup old files periodically
def cleanup_old_files():
    while True:
        time.sleep(3600)
        try:
            now = time.time()
            for f in os.listdir(DOWNLOAD_FOLDER):
                filepath = os.path.join(DOWNLOAD_FOLDER, f)
                if os.path.isfile(filepath) and now - os.path.getmtime(filepath) > 3600:
                    os.remove(filepath)
        except:
            pass

cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()

if __name__ == '__main__':
    print("=" * 60)
    print("  JIKSDROP - All Social Media Video Downloader")
    print("=" * 60)
    print("\n  Starting server on http://localhost:5000")
    print("  Open your browser and go to http://localhost:5000")
    print("\n  Press Ctrl+C to stop the server")
    print("=" * 60 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
