# **Smart HTTP Server – Python Prototype**

### Overview

Ye project ek **user-space Smart Process Manager (SPM)** aur **HTTP 1.0/1.1 WSGI-compatible web server** ka **testing-level prototype** hai.
Design focus hai: *simplicity, adaptive scaling, aur zero signal dependency.*

---

## **Architecture Highlights**

### 1. **Smart Process Manager (SPM)**

* Adaptive monitoring loop:

  * Idle zyada → kill
  * Idle zero → spawn
  * Kam worker → replenish
* Pure user-space logic, **no OS signal dependency**
* Shared memory (`multiprocessing.Value + Lock`) se atomic coordination
* **Real-time load balancing**

---

### 2. **Thread Pool Integration**

* Har worker ke andar internal thread pool
* Dynamic scaling (auto-add/remove threads)
* Non-blocking queue-based task scheduling

---

### 3. **HTTP Server Core**

* `select.epoll` based event loop
* Fully non-blocking I/O
* Supports:

  * HTTP/1.0 & HTTP/1.1
  * Keep-Alive connections
  * Chunked transfer decoding
  * Request body parsing (Content-Length + Chunked)
  * Graceful error handling

---

### 4. **WSGIHandler**

* Standard WSGI environ builder
* Flask ya custom app load kar sakta hai
* Epoll re-arming for persistent connections
* Response builder (status, headers, body merge)

Example:

```bash
python3 main.py --lode:app->app
```

Ye `app.py` file me defined `app()` function load karega.

---

### 5. **AppLoader**

* CLI se dynamically module load karta hai:

  ```
  --lode:module->function
  ```
* Safe import aur callable verification.

---

## **Performance Advantage**

| Feature         | Apache MPM (prefork) | Smart HTTP Server   |
| --------------- | -------------------- | ------------------- |
| Architecture    | C + OS signals       | Pure Python         |
| Context Switch  | Yes                  | None                |
| Adaptivity      | Fixed thresholds     | Dynamic real-time   |
| Cross-Platform  | Limited              | Fully portable      |
| Signal Handling | Required             | Not used            |
| Idle Management | Kernel waitpid       | User-space counters |

**Result:** Faster, deterministic aur predictable control.

---

## **Reliability**

* Synchronous control flow (no async signal loss)
* Shared state locking = race-free counters
* Predictable worker behavior
* Real-time metrics: *Total, Busy, Idle, KillPending*

---

## **Extendability**

Easily pluggable modules:

* Task Queue (multiprocessing.Queue)
* Logging exporter
* Graceful shutdown
* Internal thread pools per worker

---

## **Note (Prototype Limitation)**

Ye **testing aur learning purpose ke liye** prototype hai —
**Production ready nahi hai** abhi.

### Not Yet Supported:

* HTTP/2.0 aur HTTP/3.0
* TLS/SSL encryption
* Multiplexing
* ALPN negotiation
* Advanced timeout/retry control

---

## **Next Version (C++ Implementation)**

Agle version me:

* HTTP/1.0, 1.1, 2.0, 3.0 support
* Full SSL/TLS stack
* Multiplexing aur ALPN
* High-performance async I/O
* Production-grade benchmarking layer

---

## **Summary**

> Ye code ek **intelligent self-balancing user-space MPM + HTTP server prototype** hai.
> Apache prefork jaise complex, OS-signal-driven systems se ye simple, adaptive aur deterministic approach deta hai.
> Next stage me C++ rewrite ke sath ye **production-grade multi-protocol web engine** banega.

---

### Structure Summary:

| Component     | Description                               |
| ------------- | ----------------------------------------- |
| `SPMS`        | Process pool configuration class          |
| `SPM`         | Smart adaptive process manager            |
| `ThreadPool`  | Internal worker threads controller        |
| `HTTPRequest` | Header & body parser                      |
| `WSGIHandler` | WSGI app integration & response generator |
| `HTTPServer`  | Socket listener + epoll event loop        |
| `AppLoader`   | CLI-based dynamic module importer         |

---

**Author:** Jarjish Shaikh
**Version:** Prototype 0.9 (Testing Build)
**Language:** Python 3
**License:** MIT (For research and educational use)
---

## **Architecture Overview**
### **High-Level Structure**

```
                      ┌────────────────────────────┐
                      │        SPMS Manager        │
                      │  (Smart Process Manager)   │
                      └─────────────┬──────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼───────┐           ┌───────▼───────┐           ┌───────▼───────┐
│   Worker #1   │           │   Worker #2   │           │   Worker #3   │
│ (Process)     │           │ (Process)     │           │ (Process)     │
└───────┬───────┘           └───────┬───────┘           └───────┬───────┘
        │                           │                           │
┌───────▼───────┐           ┌───────▼───────┐           ┌───────▼───────┐
│ Thread Pool   │           │ Thread Pool   │           │ Thread Pool   │
│ (Dynamic N)   │           │ (Dynamic N)   │           │ (Dynamic N)   │
└───────┬───────┘           └───────┬───────┘           └───────┬───────┘
        │                           │                           │
┌───────▼────────────────────────────────────────────────────────▼───────┐
│                         HTTP Server (Epoll)                            │
│  - Accept connections                                                  │
│  - Non-blocking read/write                                             │
│  - Keep-Alive handling                                                 │
└───────┬────────────────────────────────────────────────────────┬───────┘
        │                                                        │
┌───────▼───────────┐                                ┌────────────▼─────────┐
│   HTTPRequest     │                                │     WSGIHandler      │
│  (Parser, Body)   │                                │ (App call + Response)│
└───────┬───────────┘                                └────────────┬─────────┘
        │                                                         │
        └──────────────────────────────┬──────────────────────────┘
                                       │
                               ┌───────▼──────────┐
                               │   WSGI App       │
                               │ (Flask/Custom)   │
                               └──────────────────┘
```

---

## **Flow Explanation**

1. **SPMS Manager** continuously system monitor karta hai:

   * Agar idle worker zyada hain → terminate kar deta hai
   * Agar saare busy hain → naya process spawn karta hai
   * Shared memory counters maintain karta hai

2. **Worker Process** ek **ThreadPool** manage karta hai

   * Har thread queue se ek HTTP task handle karta hai
   * Dynamic creation aur cleanup supported hai

3. **HTTPServer (Epoll)**:

   * Client connections accept karta hai
   * Non-blocking mode me read/write karta hai
   * Keep-Alive aur persistent connections maintain karta hai

4. **HTTPRequest Parser**:

   * Headers aur body parse karta hai
   * Content-Length ya Chunked encoding handle karta hai

5. **WSGIHandler**:

   * Request ko WSGI app (Flask ya custom) tak forward karta hai
   * Response headers + body merge karta hai
   * Keep-alive ya close decide karta hai

6. **SPMS Monitor Loop**:

   * Periodically workers ki health aur load analyze karta hai
   * Idle aur busy ratios ke basis par scaling decision leta hai

---
