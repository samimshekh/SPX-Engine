# smart_http_server.py
import socket
import time
import traceback
import threading
from urllib.parse import urlparse, parse_qs
import sys
import io
import importlib
import select
import errno
import threading
from queue import Queue
from multiprocessing import Process, Value
import sys
from abc import ABC, abstractmethod
import os
def log(msg):
    print(f"[INFO] {msg} pid={os.getgid()}...")

# --- Configuration for Smart Process Manager ---
class SPMS:
    def __init__(self, MinimumWorkerProcesses, MaximumAllowedIdleProcesses, LimitOfWorkerProcesses, group = None,
        name: str  = None,
        args = (),
        kwargs = {},
        daemon: bool  = None):
        # Minimum number of worker processes to start
        self.MinimumWorkerProcesses = MinimumWorkerProcesses
        # Maximum allowed idle workers before killing extras
        self.MaximumAllowedIdleProcesses = MaximumAllowedIdleProcesses
        # Absolute limit of worker processes
        self.LimitOfWorkerProcesses = LimitOfWorkerProcesses
        self.group=group
        self.name=name
        self.args=args
        self.kwargs=kwargs
        self.daemon=daemon

# --- Shared memory counters for all workers ---
idle_count__ = Value('i', 0)  # Tracks number of idle workers
kill_pending__ = Value('i', 0) # Tracks number of workers marked for termination

# --- Base class for process management ---
class baseSpm:
    def __init__(self, spms: SPMS):
        self.processes = [] # List of active Process objects
        self.spms = spms
        self.idle = False # Local flag to track if this worker is idle
    
    # Return number of kill pending workers
    def get_kill_pending(self):
        with kill_pending__.get_lock():
            return kill_pending__.value
    
    # Check if any worker needs to be killed
    def if_kill(self):
        with kill_pending__.get_lock():
            if kill_pending__.value != 0:
                return True
        return False
    
    # Gracefully exit worker if system has marked it for kill > 0 
    def if_kill_then_exit(self, func, *args, **kwargs):
        kill = False
        with kill_pending__.get_lock():
            if kill_pending__.value > 0:
                kill = True

        if kill:
            # Optional cleanup function before exit
            if func:
                func(*args, **kwargs)

            if self.idle:
                self.remove_idle_this_worker()

            with kill_pending__.get_lock():
                if kill_pending__.value > 0:
                    kill_pending__.value -= 1
                    log(f"{type(self).__name__}: (if_kill_then_exit) exit worker")
                    sys.exit(0)
        else: return False
    
    # Mark this worker as idle
    def add_idle_this_worker(self):
        if not self.idle:
            with idle_count__.get_lock():
                idle_count__.value += 1
                self.idle = True
    
    # Remove idle mark when worker becomes active
    def remove_idle_this_worker(self):
        if self.idle:
            with idle_count__.get_lock():
                idle_count__.value -= 1
                self.idle = False
    
# --- Smart Process Manager class ---
class SPM(baseSpm, ABC):
    def __init__(self, spms: SPMS):
        super().__init__(spms)
    
    # Main monitor loop to manage worker pool
    def start_monitor_loop(self, monitoring=False):
        # Start minimum required worker processes
        self.__start_minimum_workers(
            self.spms.MinimumWorkerProcesses
        )

        while True:
            # Remove dead processes from the pool
            self.__clean_dead_processes()

            # Get current idle worker count
            idle_count = self.get_idle_count_processes()

            # Set kill_pending if idle workers exceed limit
            self.__kill_pending_set(
                idle_count
            )

            # Add new worker if needed
            self.__added_new_worker(
                idle_count
            )

            # Ensure minimum workers are always running
            self.__if_minimum_added_new_worker()

            # Optional monitoring output
            if monitoring:
                idle_count = self.get_idle_count_processes()
                busy = len(self.processes) - idle_count
                Total = len(self.processes)
                kill_pending = self.get_kill_pending()

                self.monitoring(Total, kill_pending, idle_count, busy)

    # Start the minimum number of workers
    def __start_minimum_workers(self, MinimumWorkerProcesses):
        while MinimumWorkerProcesses > 0:
            p = Process(group=self.spms.group, 
                target=self.worker,
                name=self.spms.name, 
                args=self.spms.args, 
                kwargs=self.spms.kwargs, 
                daemon=self.spms.daemon)
            p.start()
            self.processes.append(p)
            MinimumWorkerProcesses -= 1

    # Clean dead worker processes
    def __clean_dead_processes(self):
        for p in self.processes[:]:
            if not p.is_alive():
                self.processes.remove(p)
    
    # Get current number of idle workers
    def get_idle_count_processes(self):
        with idle_count__.get_lock():
            return idle_count__.value
    
    # Set kill_pending if too many idle workers
    def __kill_pending_set(self, idle_count):
        if idle_count > self.spms.MaximumAllowedIdleProcesses:
            with kill_pending__.get_lock():
                kill_pending__.value = idle_count - self.spms.MinimumWorkerProcesses
    
    # Add new worker if all are busy and under limit
    def __added_new_worker(self, idle_count):
        if idle_count == 0 and len(self.processes) < self.spms.LimitOfWorkerProcesses:
            p = Process(group=self.spms.group, 
                target=self.worker,
                name=self.spms.name, 
                args=self.spms.args, 
                kwargs=self.spms.kwargs, 
                daemon=self.spms.daemon)
            p.start()
            self.processes.append(p)
    
    # Ensure minimum workers are running
    def __if_minimum_added_new_worker(self):
        if len(self.processes) < self.spms.MinimumWorkerProcesses:
            sp = self.spms.MinimumWorkerProcesses - len(self.processes) 
            self.__start_minimum_workers(
                sp
            )
    
    @abstractmethod
    def monitoring(self, Total, kill_pending, idle_count, busy):
        """Show monitoring data"""
        pass
    
    @abstractmethod
    def worker(self, *args, **kwargs):
        """Worker process logic"""
        pass

    @abstractmethod
    def run(self):
        pass


USER_MODE_CLOSED = "CLOSED"
USER_MODE_READ = "READ"
INVLID_DATA = 1
END_DATA = 2
MORE_READ = 3
MAX_T = 40
MIN_T = 10
MAX_S_A_T = 20
SEND_TIMEOUT = 10       # seconds
SEND_RETRY_DELAY = 0.02 # retry interval
WORKER_MAX_CLINTE = 100

class ThreadPool:
    def __init__(self, max_threads=5, initial_threads=2):
        self.max_threads = max_threads
        self.task_queue = Queue()
        self.threads = []
        self.lock = threading.Lock()
        self.running_threads = set()

        # start initial threads
        self._start_threads(initial_threads)

    def _worker(self):
        log(f"ThreadPool: Worker thread started.")
        while True:
            func, args, kwargs = self.task_queue.get()
            if func is None:  # stop signal
                log(f"ThreadPool: Received stop signal, shutting down worker.")
                self.task_queue.task_done()
                break
            with self.lock:
                self.running_threads.add(threading.current_thread())
            try:
                log(f"ThreadPool: Executing assigned task.")
                func(*args, **kwargs)
            finally:
                with self.lock:
                    self.running_threads.discard(threading.current_thread())
                self.task_queue.task_done()

    def _start_threads(self, n=1):
        for _ in range(n):
            t = threading.Thread(target=self._worker)
            t.daemon = False
            t.start()
            self.threads.append(t)

    def poll_run_thread(self, func, *args, **kwargs):
        """
        Task ko queue me daale aur idle thread pick karke run kare
        Agar sare threads busy hain aur max_threads allow karta hai, 
        to nayi thread create kar do
        """
        with self.lock:
            # threads busy aur max_threads allow karta hai → new thread
            if self.task_queue.qsize() >= len(self.threads) and len(self.threads) < self.max_threads:
                self._start_threads(1)

        self.task_queue.put((func, args, kwargs))
        return True

    def poll_delete_thread(self):
        """Stop last idle thread"""
        stopped = False
        with self.lock:
            if self.threads:
                self.task_queue.put((None, (), {}))  # stop signal
                t = self.threads.pop()
                stopped = True
        return stopped

    def status(self):
        with self.lock:
            total_threads = len(self.threads)
            running = len(self.running_threads)      # busy threads
            idle_threads = total_threads - running   # threads free to delete
            can_delete = idle_threads if idle_threads > 0 else 0
            can_add = max(self.max_threads - total_threads, 0)

        return can_add, can_delete 

CRLF = "\r\n"
INVLID_DATA = 1
END_DATA = 2
MORE_READ = 3

import os
def log(msg):
    print(f"[INFO] {msg} pid={os.getpid()}...")

def err_log(msg, trace):
    print(f"[ERROR] {msg}\n {trace} pid={os.getpid()}...")

class AppLoader:
    """Command-line se WSGI app load karne ke liye."""
    def __init__(self, args):
        self.args = args

    def load(self):
        lode = self.args.get('--lode')
        if not lode:
            log("'--lode' argument not provided.")
            return None
        if '->' not in lode:
            log(f"Invalid format for --lode: {lode} (expected module->function)")
            return None
        module_path, func_name = lode.split('->', 1)
        try:
            app_module = importlib.import_module(module_path)
            func = getattr(app_module, func_name)
            if not callable(func):
                log(f"'{func_name}' is not callable.")
                return None
            return func
        except Exception:
            err_log(f"Error loading app '{module_path}->{func_name}'", traceback.format_exc())
            return None

class HTTPRequest:
    """HTTP request parsing."""
    http_methods_by_version = {
        "HTTP/1.0": ["GET", "POST", "HEAD"],
        "HTTP/1.1": ["GET", "POST", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"],
        "HTTP/2.0": ["GET", "POST", "HEAD", "PUT", "DELETE", "OPTIONS", "PATCH"],
    }

    def __init__(self, conn):
        self.conn = conn
        self.method = None
        self.path = None
        self.query = None
        self.version = None
        self.headers = {}
        self.body = b''
        self.err_404 = True
        self.colose = False
    
    def read_body(self):
        chunked = self.headers.get('Transfer-Encoding', None)
        clen = int(self.headers.get('Content-Length', 0))
        body_ = b''
        err_404 = False

        chunked_r = False
        if chunked != None:
            chunked = chunked.split(', ')[-1]
            if chunked != 'chunked': pass
            else: chunked_r = True
        
        if chunked_r:
            end_loop = True
            status = MORE_READ
            body_ = b''
            body = self.body

            while end_loop:
                status, body__, body, i = self.chunked_porsess(body)

                if status == INVLID_DATA:
                    err_404 = True
                    break
                elif status == MORE_READ:
                    body_ += body__
                    while end_loop:
                        while end_loop and i > 0:
                            try:
                                chunked = self.conn.recv(min(1024, i))
                                body += chunked
                            except BlockingIOError:
                                time.sleep(0.01)
                                continue

                            if not chunked: 
                                err_404 = True
                                self.colose = True
                                end_loop = False

                                break
                            i -= len(chunked)
                else: break
            self.body = body_
        else: 
            nede_len = clen - len(self.body)
            while nede_len > 0:
                try:
                    chunked = self.conn.recv(min(1024, nede_len))
                except BlockingIOError:
                    time.sleep(0.01)
                    continue

                if not chunked: 
                    err_404 = True
                    self.colose = True
                    break

                nede_len -= len(chunked)
                self.body += chunked
        return err_404

    def chunked_porsess(self, body):
        body_ = b''
        if b'\r\n' not in body: return MORE_READ, body_, body, 3
        if body != b'':
            while True:
                try:
                    i, body__ = body.split(b'\r\n', 1)
                    i = int(i, 16)
                except  ValueError:
                    return INVLID_DATA, body_, body, 0
                
                if i == 0 and body__ == b'\r\n':
                    return END_DATA, body_, b'', 0
                elif i == 0 and (body__ == b'' or len(body__) == 1):
                    return MORE_READ, body_, body, (2 - len(body__))
                elif i == 0:
                    return INVLID_DATA, body_, body, 0

                if len(body__) >= (i + 2):
                    if body__[i:(i + 2)] != b'\r\n':
                        return INVLID_DATA, body_, body, 0
                    body_ += body__[:i]
                    body = body__[i + 2:] 
                    if not body:
                        return MORE_READ, body_, body, i - len(body__)
                else: 
                    return MORE_READ, body_, body, i - len(body__)
            
    def read_header(self):
        data = b''
        while True:
            try:
                chunk = self.conn.recv(1024)
                data += chunk
                if not chunk:
                    self.colose = True
                    break
                elif b'\r\n\r\n' in chunk:
                    break
            except BlockingIOError:
                time.sleep(0.01)
            except Exception:
                err_log("read_header error", traceback.format_exc())
                break
        return data

    def parse(self):
        data = self.read_header()
        if b'\r\n\r\n' not in data:
            return False
        try:
            headers, self.body = data.split(b'\r\n\r\n', 1)
        except Exception:
            return False
        lines = headers.decode("iso-8859-1").split("\r\n")
        first_line = lines[0]
        try:
            self.method, full_path, self.version = first_line.split(' ')
            if self.version not in self.http_methods_by_version:
                return False
            if self.method not in self.http_methods_by_version[self.version]:
                return False
            parsed_url = urlparse(full_path)
            self.path = parsed_url.path
            self.query = parsed_url.query
        except Exception:
            return False
        for line in lines[1:]:
            if not line: continue
            try:
                key, value = line.split(": ", 1)
                self.headers[key] = value
            except Exception:
                err_log("Invalid header line", traceback.format_exc())
        self.err_404 = False
        return True
    
    def send(self, data: bytes, max_retries: int = 5) -> bool:
        total_sent = 0
        data_len = len(data)
        start_time = time.time()

        while total_sent < data_len:
            try:
                sent = self.conn.send(data[total_sent:])
                if sent == 0:
                    # Socket closed by peer
                    raise ConnectionError("Connection closed during send.")
                total_sent += sent

            except (BlockingIOError, InterruptedError):
                # Resource temporarily unavailable — wait and retry
                time.sleep(SEND_RETRY_DELAY)
                continue

            except (BrokenPipeError, ConnectionResetError) as e:
                err_log(f"{type(self).__name__} safe_send: connection error fd={self.conn.fileno()}", str(e))
                self.colose = True
                return False

            except socket.timeout:
                err_log(f"{type(self).__name__} safe_send: send timeout fd={self.conn.fileno()}", "")
                return False

            except Exception:
                err_log(f"{type(self).__name__} safe_send: unexpected error fd={self.conn.fileno()}", traceback.format_exc())
                if max_retries > 0:
                    max_retries -= 1
                    time.sleep(SEND_RETRY_DELAY)
                    continue
                return False

            # Timeout safeguard
            if (time.time() - start_time) > SEND_TIMEOUT:
                err_log(f"{type(self).__name__} safe_send: total timeout fd={self.conn.fileno()}", "")
                return False

        return True


class WSGIHandler:
    """WSGI app call & HTTP response creation."""
    def __init__(self, app):
        self.app = app

    def handle(self, user, server):
        conn = user["conn"]
        log(f"{type(self).__name__}: Handling request for fd={conn.fileno()}")

        loop_break = True
        keep_alive = False
        ropen = False
        while loop_break:
            user = server.getUser(conn.fileno())
            if user['event'] <= 0: 
                log(f"{type(self).__name__}: User event not found, fd={conn.fileno()}")
                break

            ropen = False

            conn.setblocking(False)
            request = HTTPRequest(conn)
            err = True
            if request.parse():
                log(f"Client connected {conn.getpeername()}, server host {server.host}:{server.port}, requested {request.path}, fd={conn.fileno()}")
                if request.version == 'HTTP/1.1':
                    keep_alive = True

                kea = request.headers.get('Connection', '')
                if 'close' in kea:
                    keep_alive = False
                elif 'keep-alive' in kea:
                    keep_alive = True

                log(f"{type(self).__name__}: Keep-Alive set to {keep_alive}, fd={conn.fileno()}")

                if not request.read_body():
                    err = False
            if err:
                if request.colose:
                    user = server.getUser(conn.fileno())
                    if user['event'] <= 1:
                        loop_break = False
                        keep_alive = False
                    else:
                        key = conn.fileno()
                        with server.lock:
                            user = server.data.get(key, None)
                            if user:
                                server.data[key]["event"] -= 1
                                server.data[key]["user_mode"] = USER_MODE_CLOSED
                    log(f"{type(self).__name__}: Request error, closing connection fd={conn.fileno()}")
                else:
                    key = conn.fileno()
                    with server.lock:
                        user = server.data.get(key, None)
                        if user:
                            server.data[key]["event"] -= 1
                    log(f"{type(self).__name__}: Request error, keeping connection alive fd={conn.fileno()}")
                continue

            try:
                log(f"{type(self).__name__}: Re-arming epoll for fd={conn.fileno()}")
                server.epool.modify(conn.fileno(), select.EPOLLIN | select.EPOLLET | select.EPOLLONESHOT)
                ropen = True
                environ = self.build_environ(request)
                response_status = None
                response_headers = None
                def start_response(status, headers):
                    nonlocal response_status, response_headers
                    response_status = status
                    response_headers = headers

                response_body = self.app(environ, start_response)
                # Merge default headers
                default_headers = (
                    ("Server", "DemoServer/1.1"),
                    ("Connection", "keep-alive" if keep_alive else "close")
                )
                merged_dict = dict(response_headers)
                merged_dict.update(dict(default_headers))
                final_headers = list(merged_dict.items())
                body_data = b''.join(response_body)
                header_lines = "".join(f"{k}: {v}\r\n" for k, v in final_headers)
                http_response = f"HTTP/1.1 {response_status}\r\n{header_lines}\r\n".encode() + body_data
                if not request.send(http_response):
                    log(f"{type(self).__name__}: Failed to send HTTP response, fd={conn.fileno()}")
                    with server.lock:
                        user = server.data.get(key, None)
                        if user:
                            server.data[key]["event"] -= 1
                            server.data[key]["user_mode"] = USER_MODE_CLOSED
                    continue
                else:
                    log(f"{type(self).__name__}: Response sent successfully fd={conn.fileno()}")
                    
            except Exception:
                err_log(f"{type(self).__name__}: Error generating response, fd={conn.fileno()}", traceback.format_exc())
            server.decEventUser(conn.fileno())
        

        with server.lock:
            user = server.data.get(conn.fileno(), None)
            if user:
                server.data[conn.fileno()]["is_run"] = False
                log(f"{type(self).__name__}: Marking user thread inactive, (is_run=False ) fd={conn.fileno()}")
            else: log(f"{type(self).__name__}: Inactive thread cleanup attempted for missing user, fd={conn.fileno()}")

        if keep_alive and (not ropen):
            server.epool.modify(conn.fileno(), select.EPOLLIN | select.EPOLLET | select.EPOLLONESHOT)
            log(f"{type(self).__name__}: Keep-Alive enabled, resetting epoll for next request, fd={conn.fileno()}")

        elif keep_alive == False: 
            key = conn.fileno()
            server.epool.unregister(conn.fileno())
            conn.close()
            server.deleteUser(key)
            log(f"{type(self).__name__}: Connection closed (keep-alive disabled), fd={key}")

    def build_environ(self, req: HTTPRequest):
        return {
            "REQUEST_METHOD": req.method,
            "SCRIPT_NAME": '',
            "PATH_INFO": req.path,
            "QUERY_STRING": req.query,
            "SERVER_NAME": 'localhost',
            "SERVER_PORT": '80',
            "SERVER_PROTOCOL": req.version,
            "CONTENT_TYPE": req.headers.get("Content-Type", "text/plain"),
            "CONTENT_LENGTH": str(len(req.body)),
            "wsgi.version": (1, 0),
            "wsgi.input": io.BytesIO(req.body),
            "wsgi.errors": io.StringIO(),
            "wsgi.multithread": False,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
            "wsgi.url_scheme": 'http',
            **{f"HTTP_{k.upper()}": v for k,v in req.headers.items()}
        }

class HTTPServer:
    """Main server class."""
    def __init__(self, host='localhost', port=8080):
        self.host = host
        self.port = port
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.bind((host, port))
        self.s.listen(5)
        self.s.setblocking(False)

    def server_worker_start(self, smp):
        log(f"worker listening on {self.host}:{self.port} ")
        self.lock = threading.Lock()
        self.ThreadPool = ThreadPool(MAX_T, MIN_T)
        self.epool = select.epoll()
        
        self.data = {

        }
        self.serve_forever(smp)
        sys.exit(0)
    def set_app(self, app):
        self.handler = WSGIHandler(app)
    
    def incEventUser(self, fd):
        with self.lock:
            user = self.data.get(fd, None)
            if user:
                self.data[fd]["event"] += 1
    
    def decEventUser(self, fd):
        with self.lock:
            user = self.data.get(fd, None)
            if user:
                self.data[fd]["event"] -= 1
    
    def getUser(self, fd):
        with self.lock:
            return self.data.get(fd, None)
    
    def setUser(self, fd, v):
        with self.lock:
            self.data[fd] = v

    def deleteUser(self, fd):
        with self.lock:
            self.data.pop(fd, None)

    def serve_forever(self, smp):
        t_qew = []
        clint_ac = 0
        while True:
            try:
                if WORKER_MAX_CLINTE > clint_ac:
                    conn, _ = self.s.accept()
                    fd = conn.fileno()
                    self.setUser(fd, {
                        "conn": conn,
                        "event": 0,
                        "is_run": False,
                        "user_mode": USER_MODE_READ
                    })

                    log(f"{type(self).__name__}: Accepted new connection, fd={fd}")
                    conn.setblocking(False)
                    self.epool.register(fd, select.EPOLLIN | select.EPOLLET | select.EPOLLONESHOT)
                    clint_ac += 1
                else: 
                    if (len(self.data) == 0) and (len(t_qew) == 0):
                        log(f"Too many clients connected exit worker")
                        sys.exit(0)
            except BlockingIOError:
                t_qew = list(set(t_qew))
                can_add, can_delete  = self.ThreadPool.status()

                while (len(t_qew) > 0) and (can_add != 0):
                    key = t_qew.pop(0)
                    user = self.getUser(key, None)
                    if user:
                        log(f"{type(self).__name__}: Running queued task for fd={user['conn'].fileno()}")
                        self.ThreadPool.poll_run_thread(self.handler.handle, user)
                    can_add -= 1

                can_add, can_delete  = self.ThreadPool.status()
                if can_delete > MAX_S_A_T: 
                    i = can_delete - MAX_S_A_T 
                    log(f"{type(self).__name__}: MAX_S_A_T poll_delete_thread {i}")
                    while i > 0:
                        self.ThreadPool.poll_delete_thread()
                        i -= 1
            except Exception:
                err_log("accept error", traceback.format_exc())

            if (len(self.data) == 0) and (len(t_qew) == 0):
                smp.if_kill_then_exit(None)
                smp.add_idle_this_worker()
           
            for key, event in self.epool.poll(0.01):
                user = self.getUser(key)
                log(f"{type(self).__name__}: Detected epoll event fd={key}, event={event}")

                if user: 
                    if event & select.EPOLLIN:
                        with self.lock:
                            user = self.data.get(key, None)
                            if user:
                                self.data[key]["event"] += 1
                            else:
                                log(f"{type(self).__name__}: Event found but user data missing during event increment, fd={key}")
                                self.epool.unregister(key)
                        if not user["is_run"]:  
                            log(f"{type(self).__name__}: Event received, marking user as active, fd={key}")
                            can_add, can_delete  = self.ThreadPool.status()
                            if can_add != 0:
                                with self.lock:
                                    user = self.data.get(key, None)
                                    if user:
                                        self.data[key]["is_run"] = True
                                    else:
                                        log(f"{type(self).__name__}: Event received for unknown user, unregistering fd={key}")
                                        self.epool.unregister(key)
                                if user:
                                    smp.add_idle_this_worker()

                                    log(f"{type(self).__name__}: Dispatching worker thread for fd={key}")
                                    self.ThreadPool.poll_run_thread(self.handler.handle, user, self)
                            else:
                                smp.remove_idle_this_worker() 

                                with self.lock:
                                    user = self.data.get(key, None)
                                    if user:
                                        self.data[key]["is_run"] = False
                                    else:
                                        log(f"{type(self).__name__}: Event received for unknown user, unregistering fd={key}")
                                        self.epool.unregister(key)
                                t_qew.append(key)
                                log(f"{type(self).__name__}: No free worker, queued fd={key} for later execution")
                        else: log(f"{type(self).__name__}: handler already active for fd={key}")
                    else:
                        if user["user_mode"] == USER_MODE_CLOSED and user["event"] <= 0:
                            self.epool.unregister(key)
                            user["conn"].close()
                            self.deleteUser(key)
                            log(f"{type(self).__name__}: Closing and unregistering socket fd={key}")
                        else:
                            with self.lock:
                                user = self.data.get(key, None)
                                if user:
                                    self.data[key]["event"] += 1
                                    self.data[key]["user_mode"] = USER_MODE_CLOSED
                            log(f"{type(self).__name__}: Close event registered, pending cleanup for fd={key}")
                else:
                    log(f"{type(self).__name__}: faind event but not faind user {key}")
                    try:
                        self.epool.unregister(key) 
                    except OSError: 
                        err_log(f"OSError faind event but not faind user {key}", traceback.format_exc()) 
                    except Exception:
                        pass

def parse_args():
    result = {}
    args = sys.argv[1:]
    for arg in args:
        if ':' in arg:
            key, value = arg.split(':', 1)
            result[key] = value
        else:
            log(f"Invalid argument format: {arg}")
            return {}
    return result

class MyWorkerManager(SPM):
    def __init__(self, spms):
        args = parse_args()
        loader = AppLoader(args)
        app = loader.load()
        if app:
            self.server = HTTPServer()
            self.server.set_app(app)
        super().__init__(spms)
    
    def worker(self):
        self.server.server_worker_start(self)
        sys.exit(0)

    # Print monitoring info
    def monitoring(self, Total, kill_pending, idle, busy):
        #print(f"[Monitor] Total={Total:2d} | Busy={busy:2d} | Idle={idle:2d} | KillPending={kill_pending:2d}", end="\n")
        time.sleep(1)

    # Start the manager
    def run(self):
        self.start_monitor_loop(True)

if __name__ == "__main__":
    # --- Configuration ---
    config  = SPMS(
        MinimumWorkerProcesses=1,
        MaximumAllowedIdleProcesses=3, 
        LimitOfWorkerProcesses=5, 
    )

    spm = MyWorkerManager(config)
    spm.run()