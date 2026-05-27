import { useQuery } from "@tanstack/react-query";
import { Link, Navigate } from "react-router-dom";
import { organizationsApi } from "../api/organizations";
import { ErrorNotice } from "../components/ErrorNotice";

export function HomePage() {
  const organizations = useQuery({
    queryKey: ["organizations"],
    queryFn: organizationsApi.list,
  });
  if (organizations.isLoading) return <p className="muted">载入组织...</p>;
  if (organizations.error) return <ErrorNotice error={organizations.error} />;
  if (organizations.data?.length) {
    return <Navigate replace to={`/orgs/${organizations.data[0].id}/issues`} />;
  }
  return (
    <section className="empty-state">
      <h1>还没有组织</h1>
      <Link className="button" to="/organizations">
        创建第一个组织
      </Link>
    </section>
  );
}
