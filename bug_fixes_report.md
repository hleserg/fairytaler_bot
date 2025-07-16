# Bug Fixes Report

This report details 3 significant bugs found and fixed in the Telegram storytelling bot codebase.

## Bug 1: Resource Leak - Temporary Files Not Cleaned Up

### **Severity**: High
**Type**: Memory/Disk Space Leak
**Location**: `bot.py` lines 298-315, audio_cmd function, test_cmd function

### **Problem Description**
The `synthesize_tts` function creates temporary files using `tempfile.NamedTemporaryFile(delete=False)` but never cleans them up. This leads to:
- Gradual disk space consumption over time
- Potential disk space exhaustion on systems with limited storage
- Poor resource management practices

### **Root Cause**
```python
with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as f:
    # File is created but never deleted
```

The `delete=False` parameter prevents automatic cleanup, but no manual cleanup was implemented.

### **Fix Implementation**
1. **Added proper exception handling** with try/finally blocks in `synthesize_tts`
2. **Implemented cleanup in caller functions** (`audio_cmd`, `test_cmd`) using try/finally
3. **Added error handling** for cleanup operations to prevent secondary failures

### **Code Changes**
- Modified `synthesize_tts` to clean up files on exceptions
- Updated `audio_cmd` to clean up temporary files after sending
- Updated `test_cmd` to clean up temporary files after sending
- Added `os.unlink()` calls with proper error handling

### **Impact**
- Prevents disk space leaks
- Improves system stability for long-running bot instances
- Better resource management

---

## Bug 2: Race Condition with Global IAM Token

### **Severity**: Medium-High
**Type**: Concurrency/Thread Safety Issue
**Location**: `bot.py` lines 20, 43-53, 272

### **Problem Description**
The global `iam_token` variable is accessed and modified from multiple threads without proper synchronization:
- Background scheduler thread updates the token every 24 hours
- Main application threads read and potentially update the token
- No locking mechanism protects concurrent access

### **Root Cause**
```python
# Global variable accessed from multiple threads
iam_token = None

def update_token():
    global iam_token
    iam_token = new_token  # Unsafe concurrent access

async def synthesize_tts():
    global iam_token
    if not iam_token:  # Race condition here
        iam_token = fetch_iam_token()
```

### **Fix Implementation**
1. **Added threading.Lock()** for synchronizing access to `iam_token`
2. **Protected all read/write operations** with the lock
3. **Improved token update logic** with better error handling
4. **Enhanced scheduler error handling** with fallback mechanisms

### **Code Changes**
- Added `iam_token_lock = threading.Lock()`
- Wrapped all token access in `with iam_token_lock:` blocks
- Improved scheduler initialization with try/catch
- Added logging for better debugging

### **Impact**
- Eliminates race conditions in token management
- Prevents authentication failures due to corrupted token state
- Improves application reliability in multi-threaded environment

---

## Bug 3: Insufficient Error Handling for Subprocess Calls

### **Severity**: Medium
**Type**: Error Handling/Reliability Issue
**Location**: `bot.py` lines 24-36 (yc CLI), 307-315 (ffmpeg)

### **Problem Description**
Subprocess calls to external tools (`yc` CLI and `ffmpeg`) lack proper error handling:
- No validation of tool availability before execution
- Insufficient timeout handling
- Poor error messages and logging
- Silent failures could lead to unexpected behavior

### **Root Cause**
```python
# Insufficient error handling
result = subprocess.run(['yc', 'iam', 'create-token'], timeout=20)
# What if 'yc' is not installed? What if timeout is too short?

result = subprocess.run(['ffmpeg', '-y', '-i', ogg_path, ...])
# No timeout, no validation of ffmpeg availability
```

### **Fix Implementation**
1. **Added tool availability checks** using `which` command
2. **Improved timeout handling** with specific timeout exceptions
3. **Enhanced error messages** with detailed logging
4. **Added validation** for subprocess outputs
5. **Implemented graceful degradation** for optional features

### **Code Changes**
For `yc` CLI:
- Check tool availability with `which yc`
- Increased timeout from 20 to 30 seconds
- Added specific exception handling for TimeoutExpired and FileNotFoundError
- Enhanced token validation (length check)

For `ffmpeg`:
- Check tool availability before conversion
- Added 60-second timeout for conversion process
- Validate output file size and existence
- Graceful degradation when ffmpeg is unavailable

### **Impact**
- More reliable external tool integration
- Better user experience with informative error messages
- Graceful handling of missing dependencies
- Improved debugging capabilities

---

## Summary

These fixes address critical issues that could affect the bot's reliability and system resources:

1. **Resource Management**: Prevents disk space leaks that could crash the system
2. **Thread Safety**: Eliminates race conditions in authentication token handling
3. **Error Resilience**: Improves handling of external dependencies and system calls

The fixes maintain backward compatibility while significantly improving the application's robustness and production readiness.

## Testing Recommendations

1. **Resource Leak Testing**: Run the bot for extended periods and monitor disk usage
2. **Concurrency Testing**: Test multiple simultaneous TTS requests
3. **Dependency Testing**: Test bot behavior when `yc` or `ffmpeg` are not available
4. **Error Recovery Testing**: Test token refresh scenarios and network failures