import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { api } from "@/api/hooks";
import { clearSession, loadSession, saveSession, type Session } from "@/api/client";

interface AuthContextValue {
  session: Session | null;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  setSession: (session: Session) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSessionState] = useState<Session | null>(() => loadSession());

  useEffect(() => {
    // 令牌在 localStorage 里，别的标签页登出时这里要跟着登出
    const onStorage = (event: StorageEvent) => {
      if (event.key === "cbc.session") setSessionState(loadSession());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setSession = useCallback((next: Session) => {
    saveSession({
      user_id: next.userId,
      username: next.username,
      access_token: next.access,
      refresh_token: next.refresh,
      token_type: "bearer",
    });
    setSessionState(next);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const tokens = await api.login(username, password);
    setSessionState(saveSession(tokens));
  }, []);

  const register = useCallback(async (username: string, password: string) => {
    const tokens = await api.register(username, password);
    setSessionState(saveSession(tokens));
  }, []);

  const logout = useCallback(async () => {
    const current = loadSession();
    if (current?.refresh) {
      try {
        await api.logout(current.refresh);
      } catch {
        // 登出失败不影响本地清理：令牌会自然过期，不能把人锁在页面里
      }
    }
    clearSession();
    setSessionState(null);
  }, []);

  const value = useMemo(
    () => ({ session, login, register, logout, setSession }),
    [session, login, register, logout, setSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return context;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const location = useLocation();
  if (!session) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <>{children}</>;
}
