import { Navigate, Route, Routes } from "react-router-dom";

import { RequireAuth } from "@/auth/session";
import { Layout } from "@/components/Layout";
import { Account } from "@/pages/Account";
import { Dashboard } from "@/pages/Dashboard";
import { DatasetDetail } from "@/pages/DatasetDetail";
import { ExportCenter } from "@/pages/ExportCenter";
import { Login } from "@/pages/Login";
import { Register } from "@/pages/Register";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="/datasets/:datasetId" element={<DatasetDetail />} />
        <Route path="/export" element={<ExportCenter />} />
        <Route path="/account" element={<Account />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
