import { NavLink } from "react-router";
import "./workspaceSwitcher.css";

export function WorkspaceSwitcher() {
  return (
    <nav className="workspace-switcher" aria-label="Choose interface">
      <NavLink to="/workspace">Workspace</NavLink>
      <NavLink to="/canvas">Canvas</NavLink>
      <NavLink to="/report">Report</NavLink>
      <NavLink to="/slides">Slides</NavLink>
      <NavLink to="/figure">Figure</NavLink>
      <NavLink to="/pinpoint">Pinpoint</NavLink>
    </nav>
  );
}
