//! The calls into Windows. Every `unsafe` block of the exe is in this module.

use std::ffi::{OsString, c_void};
use std::os::windows::ffi::OsStringExt;
use std::os::windows::io::AsRawHandle;
use std::path::{Path, PathBuf};
use std::process::Child;
use std::ptr;
use std::time::{Duration, Instant};

use windows::Win32::Foundation::{
    ERROR_ALREADY_EXISTS, ERROR_CANCELLED, ERROR_FILE_TOO_LARGE, ERROR_TIMEOUT, FILETIME, GetLastError, HANDLE, HWND,
    WAIT_FAILED, WAIT_OBJECT_0,
};
use windows::Win32::Networking::WinHttp::{
    WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY, WINHTTP_FLAG_SECURE, WINHTTP_OPEN_REQUEST_FLAGS, WINHTTP_QUERY_FLAG_NUMBER,
    WINHTTP_QUERY_STATUS_CODE, WinHttpCloseHandle, WinHttpConnect, WinHttpOpen, WinHttpOpenRequest,
    WinHttpQueryHeaders, WinHttpReadData, WinHttpReceiveResponse, WinHttpSendRequest, WinHttpSetTimeouts,
};
use windows::Win32::Security::Cryptography::{
    BCRYPT_SHA256_ALG_HANDLE, BCRYPT_USE_SYSTEM_PREFERRED_RNG, BCryptGenRandom, BCryptHash,
};
use windows::Win32::System::Com::{
    CLSCTX_INPROC_SERVER, COINIT_APARTMENTTHREADED, CoCreateInstance, CoInitializeEx, CoTaskMemFree, CoUninitialize,
    IPersistFile,
};
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, PROCESSENTRY32W, Process32FirstW, Process32NextW, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JOB_OBJECT_LIMIT_BREAKAWAY_OK, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JobObjectExtendedLimitInformation, SetInformationJobObject,
    TerminateJobObject,
};
use windows::Win32::System::Threading::{
    CreateEventW, EVENT_MODIFY_STATE, GetProcessTimes, INFINITE, OpenEventW, OpenProcess, PROCESS_NAME_WIN32,
    PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_SYNCHRONIZE, PROCESS_TERMINATE, QueryFullProcessImageNameW, SetEvent,
    TerminateProcess, WaitForMultipleObjects, WaitForSingleObject,
};
use windows::Win32::UI::Shell::{
    FOS_FORCEFILESYSTEM, FOS_PICKFOLDERS, FileOpenDialog, IFileOpenDialog, IShellLinkW, KF_FLAG_DEFAULT,
    SHGetKnownFolderPath, SIGDN_FILESYSPATH, ShellExecuteW, ShellLink,
};
use windows::Win32::UI::WindowsAndMessaging::{
    IDYES, MB_ICONERROR, MB_ICONINFORMATION, MB_ICONQUESTION, MB_OK, MB_YESNO, MESSAGEBOX_RESULT, MESSAGEBOX_STYLE,
    MessageBoxW, SW_SHOWNORMAL,
};
use windows::core::{Error, GUID, HSTRING, Interface, Owned, PCWSTR, PWSTR, Result, w};

// `ShellExecuteW` answers with a number above this when it worked.
const SHELL_EXECUTE_WORKED: usize = 32;
// What the processes of a job that is ended exit with.
const ENDED_EXIT_CODE: u32 = 1;
// How long a web server gets to be found and to connect, and then for each part of its answer, in milliseconds.
const HTTP_CONNECT_PATIENCE: i32 = 15_000;
const HTTP_ANSWER_PATIENCE: i32 = 30_000;
// How much of an answer is read at a time.
const HTTP_CHUNK: u32 = 64 * 1024;
// The longest path Windows has, in UTF-16 units.
const LONGEST_PATH: usize = 32_768;

/// Returns one of the folders Windows knows by an id, such as the user's programs or their desktop, wherever it has
/// been moved to.
pub fn known_folder(id: &GUID) -> Result<PathBuf> {
    // SAFETY: The id outlives the call, and no token asks for the current user's folder.
    let path = unsafe { SHGetKnownFolderPath(id, KF_FLAG_DEFAULT, None) }?;
    // SAFETY: On success the path is a string Windows allocated, ending in a null.
    let folder = PathBuf::from(HSTRING::from_wide(unsafe { path.as_wide() }).to_os_string());
    // SAFETY: The string is the caller's to free, with this function, and isn't read again.
    unsafe { CoTaskMemFree(Some(path.as_ptr().cast())) };
    Ok(folder)
}

/// Shows what went wrong in a window of its own and waits for it to be closed.
pub fn show_failure(title: &str, text: &str) {
    message_box(title, text, MB_OK | MB_ICONERROR);
}

/// Tells something in a window of its own and waits for it to be closed.
pub fn show_note(title: &str, text: &str) {
    message_box(title, text, MB_OK | MB_ICONINFORMATION);
}

/// Asks a yes or no question in a window of its own, and returns whether the answer was yes.
pub fn ask(title: &str, question: &str) -> bool {
    message_box(title, question, MB_YESNO | MB_ICONQUESTION) == IDYES
}

fn message_box(title: &str, text: &str, style: MESSAGEBOX_STYLE) -> MESSAGEBOX_RESULT {
    // SAFETY: Both strings outlive the call, and a message needs no owner window.
    unsafe { MessageBoxW(None, &HSTRING::from(text), &HSTRING::from(title), style) }
}

/// Writes a shortcut that opens `target` with `arguments`, in place of one already at `shortcut`. Its icon is the
/// target's own.
pub fn create_shortcut(shortcut: &Path, target: &Path, arguments: &str, description: &str) -> Result<()> {
    let _com = Com::start()?;
    // SAFETY: COM is started on this thread for as long as `_com` lives, which is past the last use of the link, and
    // every string outlives the call it is passed to.
    unsafe {
        let link: IShellLinkW = CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER)?;
        link.SetPath(&HSTRING::from(target))?;
        link.SetArguments(&HSTRING::from(arguments))?;
        link.SetDescription(&HSTRING::from(description))?;
        link.cast::<IPersistFile>()?.Save(&HSTRING::from(shortcut), true)
    }
}

/// Asks for a folder in Windows' own window, over the window with this handle. Returns None when it was closed
/// without one being chosen.
pub fn pick_folder(owner: isize, title: &str) -> Result<Option<PathBuf>> {
    let _com = Com::start()?;
    // SAFETY: COM is started on this thread for as long as `_com` lives, which is past the last use of the dialog.
    // The owner is a window of this thread that outlives the call, the title outlives it too, and the path is a
    // string Windows allocated for the caller to free, which isn't read after it is.
    unsafe {
        let dialog: IFileOpenDialog = CoCreateInstance(&FileOpenDialog, None, CLSCTX_INPROC_SERVER)?;
        dialog.SetOptions(dialog.GetOptions()? | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM)?;
        dialog.SetTitle(&HSTRING::from(title))?;
        match dialog.Show(Some(HWND(ptr::with_exposed_provenance_mut(owner.cast_unsigned())))) {
            Err(error) if error.code() == ERROR_CANCELLED.to_hresult() => return Ok(None),
            shown => shown?,
        }
        let path = dialog.GetResult()?.GetDisplayName(SIGDN_FILESYSPATH)?;
        let folder = PathBuf::from(HSTRING::from_wide(path.as_wide()).to_os_string());
        CoTaskMemFree(Some(path.as_ptr().cast()));
        Ok(Some(folder))
    }
}

/// Opens an address in the browser the user has chosen.
pub fn open_in_browser(url: &str) -> Result<()> {
    let _com = Com::start()?;
    // SAFETY: Both strings outlive the call, and the rest is left for Windows to choose.
    let answer = unsafe { ShellExecuteW(None, w!("open"), &HSTRING::from(url), None, None, SW_SHOWNORMAL) };
    if answer.0.addr() > SHELL_EXECUTE_WORKED { Ok(()) } else { Err(Error::from_thread()) }
}

/// A web address, in the parts Windows takes one in.
#[derive(Debug, PartialEq)]
pub struct WebAddress {
    /// Whether it is reached over HTTPS.
    pub secure: bool,
    pub host: String,
    pub port: u16,
    /// What follows the host, from its first slash.
    pub path: String,
}

/// Fetches a web address, following it to wherever it has moved, and returns the status the server answered with
/// and what it sent. Windows makes the connection, so its proxy and its certificates are the user's own.
///
/// An answer longer than `limit` bytes is an error.
pub fn http_get(address: &WebAddress, agent: &str, limit: usize) -> Result<(u32, Vec<u8>)> {
    let flags = if address.secure { WINHTTP_FLAG_SECURE } else { WINHTTP_OPEN_REQUEST_FLAGS(0) };
    let mut status = 0_u32;
    let mut status_size = u32::try_from(size_of_val(&status)).unwrap_or(u32::MAX);
    let mut body = Vec::new();
    let mut chunk = vec![0_u8; HTTP_CHUNK as usize];
    // SAFETY: Each handle is checked as it is opened, is closed when its value is dropped, and is dropped before
    // the one it was opened from. The strings outlive the calls they are passed to. The status is read into a
    // number of the size the call is told. Each read is told the chunk's own length, and writes how much of it was
    // filled.
    unsafe {
        let session = Internet::opened(WinHttpOpen(
            &HSTRING::from(agent),
            WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY,
            PCWSTR::null(),
            PCWSTR::null(),
            0,
        ))?;
        WinHttpSetTimeouts(
            session.0,
            HTTP_CONNECT_PATIENCE,
            HTTP_CONNECT_PATIENCE,
            HTTP_ANSWER_PATIENCE,
            HTTP_ANSWER_PATIENCE,
        )?;
        let connection = Internet::opened(WinHttpConnect(session.0, &HSTRING::from(&address.host), address.port, 0))?;
        let request = Internet::opened(WinHttpOpenRequest(
            connection.0,
            w!("GET"),
            &HSTRING::from(&address.path),
            PCWSTR::null(),
            PCWSTR::null(),
            ptr::null(),
            flags,
        ))?;
        WinHttpSendRequest(request.0, None, None, 0, 0, 0)?;
        WinHttpReceiveResponse(request.0, ptr::null_mut())?;
        WinHttpQueryHeaders(
            request.0,
            WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
            PCWSTR::null(),
            Some((&raw mut status).cast::<c_void>()),
            &raw mut status_size,
            ptr::null_mut(),
        )?;
        loop {
            let mut read = 0_u32;
            WinHttpReadData(request.0, chunk.as_mut_ptr().cast::<c_void>(), HTTP_CHUNK, &raw mut read)?;
            if read == 0 {
                return Ok((status, body));
            }
            body.extend_from_slice(&chunk[..read as usize]);
            if body.len() > limit {
                return Err(ERROR_FILE_TOO_LARGE.into());
            }
        }
    }
}

/// A handle of Windows' HTTP calls, which is closed when this value is dropped.
struct Internet(*mut c_void);

impl Internet {
    /// Takes what a call that opens a handle returned, which is null when it couldn't.
    fn opened(handle: *mut c_void) -> Result<Self> {
        if handle.is_null() { Err(Error::from_thread()) } else { Ok(Self(handle)) }
    }
}

impl Drop for Internet {
    fn drop(&mut self) {
        // SAFETY: The handle is open, and this value's alone to close. A handle that won't close is only left open.
        let _ = unsafe { WinHttpCloseHandle(self.0) };
    }
}

/// Returns the SHA-256 hash of some bytes.
pub fn sha256(bytes: &[u8]) -> Result<[u8; 32]> {
    let mut hash = [0; 32];
    // SAFETY: Windows keeps the algorithm's handle open itself, and the hash is the length this algorithm writes.
    unsafe { BCryptHash(BCRYPT_SHA256_ALG_HANDLE, None, bytes, &mut hash) }.ok()?;
    Ok(hash)
}

/// Returns random bytes from the system's generator, for a secret no other program can guess.
pub fn random_bytes<const LENGTH: usize>() -> Result<[u8; LENGTH]> {
    let mut bytes = [0; LENGTH];
    // SAFETY: With this flag no algorithm is opened, and the bytes are written into the whole of the array.
    unsafe { BCryptGenRandom(None, &mut bytes, BCRYPT_USE_SYSTEM_PREFERRED_RNG) }.ok()?;
    Ok(bytes)
}

/// A process on this machine, as Windows lists them.
#[derive(Clone, Debug, PartialEq)]
pub struct Process {
    pub id: u32,
    /// The process that started it, which may have ended, and whose id may since be another's.
    pub parent: u32,
    /// Its program, when it can be asked, which another user's can't.
    pub program: Option<PathBuf>,
    /// When it started, in Windows' ticks, which tells it from a process that had its id before. Zero when unknown.
    pub started: u64,
}

/// Returns every process running now.
pub fn processes() -> Result<Vec<Process>> {
    // SAFETY: A snapshot of the processes needs no process id, and the handle it returns is this value's alone to
    // close.
    let snapshot = unsafe { Owned::new(CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)?) };
    let mut entry =
        PROCESSENTRY32W { dwSize: u32::try_from(size_of::<PROCESSENTRY32W>()).unwrap_or(0), ..Default::default() };
    let mut listed = Vec::new();
    // SAFETY: The snapshot is open, and the entry is of the size it is told, which is all each call writes.
    let mut next = unsafe { Process32FirstW(*snapshot, &raw mut entry) };
    while next.is_ok() {
        let (program, started) = describe(entry.th32ProcessID);
        listed.push(Process { id: entry.th32ProcessID, parent: entry.th32ParentProcessID, program, started });
        // SAFETY: As for the first.
        next = unsafe { Process32NextW(*snapshot, &raw mut entry) };
    }
    Ok(listed)
}

/// Returns a process's program and when it started, as far as it can be asked.
fn describe(id: u32) -> (Option<PathBuf>, u64) {
    // SAFETY: Asking for this much needs no more than the process's id, and the handle is this value's alone to close.
    let Ok(process) = (unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, id) }) else {
        return (None, 0);
    };
    // SAFETY: The handle was just opened, and nothing else closes it.
    let process = unsafe { Owned::new(process) };
    (program(*process), started(*process).unwrap_or(0))
}

fn program(process: HANDLE) -> Option<PathBuf> {
    let mut name = vec![0_u16; LONGEST_PATH];
    let mut length = u32::try_from(name.len()).unwrap_or(u32::MAX);
    // SAFETY: The handle is open, and the call is told the buffer's length, and writes how much of it it filled.
    unsafe { QueryFullProcessImageNameW(process, PROCESS_NAME_WIN32, PWSTR(name.as_mut_ptr()), &raw mut length) }
        .ok()?;
    let length = usize::try_from(length).ok()?;
    Some(PathBuf::from(OsString::from_wide(name.get(..length)?)))
}

fn started(process: HANDLE) -> Option<u64> {
    let (mut created, mut exited, mut kernel, mut user) = Default::default();
    // SAFETY: The handle is open, and each time is written into one of the four the call is given.
    unsafe {
        GetProcessTimes(process, &raw mut created, &raw mut exited, &raw mut kernel, &raw mut user).ok()?;
    }
    let FILETIME { dwHighDateTime: high, dwLowDateTime: low } = created;
    Some(u64::from(high) << 32 | u64::from(low))
}

/// Ends the processes, each only if it is still the one that started then, and returns once they have all ended or
/// `patience` is up. One that ended already, or can't be opened, is passed over.
pub fn end_processes(processes: &[Process], patience: Duration) -> Result<()> {
    let mut ending = Vec::new();
    for process in processes {
        let access = PROCESS_TERMINATE | PROCESS_SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION;
        // SAFETY: Opening a process needs only its id, and the handle is this value's alone to close.
        let Ok(handle) = (unsafe { OpenProcess(access, false, process.id) }) else {
            continue;
        };
        // SAFETY: The handle was just opened, and nothing else closes it.
        let handle = unsafe { Owned::new(handle) };
        if started(*handle).unwrap_or(0) != process.started {
            continue;
        }
        // SAFETY: The handle is open, with the right to end the process.
        unsafe { TerminateProcess(*handle, ENDED_EXIT_CODE) }?;
        ending.push(handle);
    }
    let until = Instant::now() + patience;
    for handle in ending {
        let left = until.saturating_duration_since(Instant::now());
        let left = u32::try_from(left.as_millis()).unwrap_or(u32::MAX);
        // SAFETY: The handle is open, with the right to wait for the process.
        match unsafe { WaitForSingleObject(*handle, left) } {
            WAIT_OBJECT_0 => {}
            WAIT_FAILED => return Err(Error::from_thread()),
            _ => return Err(ERROR_TIMEOUT.into()),
        }
    }
    Ok(())
}

/// A group of processes that Windows ends when this value is dropped, or when this exe ends in any other way.
pub struct Job(Owned<HANDLE>);

impl Job {
    pub fn new() -> Result<Self> {
        // SAFETY: A job needs neither attributes nor a name, and the handle it returns is this value's alone to close.
        let job = unsafe { Owned::new(CreateJobObjectW(None, PCWSTR::null())?) };
        let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        // A process may still leave the job by asking to as it starts, which the tool does for work that is to go on
        // after the app has quit.
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK;
        let size = u32::try_from(size_of_val(&limits)).unwrap_or(u32::MAX);
        // SAFETY: The pointer is to a structure of the kind and the size the call is told, which outlives the call.
        unsafe {
            SetInformationJobObject(*job, JobObjectExtendedLimitInformation, (&raw const limits).cast::<c_void>(), size)
        }?;
        Ok(Self(job))
    }

    /// Puts a process in the job, and with it every process it starts from then on.
    pub fn add(&self, process: &Child) -> Result<()> {
        // SAFETY: Both handles are open: the job's for as long as `self`, the process's for as long as `process`.
        unsafe { AssignProcessToJobObject(*self.0, HANDLE(process.as_raw_handle())) }
    }

    /// Ends every process in the job now.
    pub fn end(&self) -> Result<()> {
        // SAFETY: The handle is open for as long as `self`.
        unsafe { TerminateJobObject(*self.0, ENDED_EXIT_CODE) }
    }
}

/// A signal with a name, which any process of this user can raise and one can wait for.
pub struct Signal(Owned<HANDLE>);

// SAFETY: The handle is to a Windows event, which may be waited for and raised from any thread, and nothing else has
// a copy of it.
unsafe impl Send for Signal {}

impl Signal {
    /// Makes the signal, or opens the one of that name, and returns it with whether it was made here.
    pub fn create(name: &str) -> Result<(Self, bool)> {
        // SAFETY: The name outlives the call, and the handle it returns is this value's alone to close. The event
        // lowers itself once a wait has seen it, and starts lowered.
        let signal = unsafe { Owned::new(CreateEventW(None, false, false, &HSTRING::from(name))?) };
        // SAFETY: Reads what the call above left for this thread, which is this error when the event was there.
        let made = unsafe { GetLastError() } != ERROR_ALREADY_EXISTS;
        Ok((Self(signal), made))
    }

    /// Returns the signal of that name, or None when no process has made one.
    pub fn open(name: &str) -> Option<Self> {
        // SAFETY: The name outlives the call, and the handle it returns is this value's alone to close.
        unsafe {
            OpenEventW(EVENT_MODIFY_STATE, false, &HSTRING::from(name)).ok().map(|signal| Self(Owned::new(signal)))
        }
    }

    pub fn raise(&self) -> Result<()> {
        // SAFETY: The handle is open for as long as `self`.
        unsafe { SetEvent(*self.0) }
    }
}

/// Waits until one of the signals is raised, and returns its place among them.
pub fn wait_for_any(signals: &[&Signal]) -> Result<usize> {
    let handles: Vec<HANDLE> = signals.iter().map(|signal| *signal.0).collect();
    // SAFETY: Every handle is open for as long as its signal, which is borrowed for the whole call.
    let raised = unsafe { WaitForMultipleObjects(&handles, false, INFINITE) };
    if raised == WAIT_FAILED {
        return Err(Error::from_thread());
    }
    // Without a time limit, what is left is the place of the one that was raised.
    Ok(raised.0 as usize)
}

/// COM on the current thread, from when it is started until it is dropped.
struct Com;

impl Com {
    fn start() -> Result<Self> {
        // SAFETY: Each start that succeeds, which includes one on a thread that had COM already, is matched by the
        // stop in `drop`.
        unsafe { CoInitializeEx(None, COINIT_APARTMENTTHREADED) }.ok()?;
        Ok(Self)
    }
}

impl Drop for Com {
    fn drop(&mut self) {
        // SAFETY: Matches the start that made this value, on the same thread, since the value isn't `Send`.
        unsafe { CoUninitialize() };
    }
}
