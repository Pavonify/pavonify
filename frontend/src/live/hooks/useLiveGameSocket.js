import { useEffect, useRef, useState } from "react";

const CONNECTION_STATES = {
  IDLE: "idle",
  CONNECTING: "connecting",
  OPEN: "open",
  CLOSED: "closed",
  ERROR: "error",
};

export function useLiveGameSocket(url, handlers, { reconnectIntervalMs = 2000 } = {}) {
  const [status, setStatus] = useState(CONNECTION_STATES.IDLE);
  const socketRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const handlersRef = useRef(handlers);

  handlersRef.current = handlers;

  useEffect(() => {
    if (!url) {
      return undefined;
    }

    let cancelled = false;

    const connect = () => {
      if (cancelled) {
        return;
      }

      setStatus(CONNECTION_STATES.CONNECTING);
      const ws = new WebSocket(url);
      socketRef.current = ws;

      ws.onopen = () => {
        if (!cancelled) {
          setStatus(CONNECTION_STATES.OPEN);
        }
      };

      ws.onmessage = event => {
        try {
          const data = JSON.parse(event.data);
          const handler = handlersRef.current?.[data?.type];
          if (typeof handler === "function") {
            handler(data);
          }
        } catch (error) {
          // eslint-disable-next-line no-console
          console.warn("Failed to parse websocket message", error);
        }
      };

      ws.onclose = () => {
        if (cancelled) {
          return;
        }
        setStatus(CONNECTION_STATES.CLOSED);
        if (reconnectIntervalMs > 0) {
          reconnectTimeoutRef.current = setTimeout(connect, reconnectIntervalMs);
        }
      };

      ws.onerror = () => {
        if (!cancelled) {
          setStatus(CONNECTION_STATES.ERROR);
        }
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (socketRef.current) {
        try {
          socketRef.current.close();
        } catch (error) {
          // ignore
        }
      }
      socketRef.current = null;
    };
  }, [url, reconnectIntervalMs]);

  return status;
}

export default useLiveGameSocket;
