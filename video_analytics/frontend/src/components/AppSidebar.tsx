import { BarChart3, Film, Plus, RadioTower, Upload } from "lucide-react";
import { NavLink } from "@/components/NavLink";
import { useLocation } from "react-router-dom";
import type { ComponentType } from "react";

type NavItem =
  | {
      title: string;
      url: string;
      icon: ComponentType<{ className?: string }>;
    }
  | {
      title: string;
      icon: ComponentType<{ className?: string }>;
      children: { title: string; url: string }[];
    };

const navItems: NavItem[] = [
  { title: "Upload Video", url: "/upload", icon: Upload },
  { title: "Add Camera", url: "/live-stream", icon: Plus },
  {
    title: "Processed Video",
    icon: Film,
    children: [
      { title: "Upload videos", url: "/processed-video/processed-videos" },
    ],
  },
  { title: "Live Streams", url: "/live-previews", icon: RadioTower },
{ title: "Analytics", url: "/analytics", icon: BarChart3 },
];


export function AppSidebar() {
  const location = useLocation();

  return (
    <aside className="hidden md:flex flex-col w-60 h-full bg-card border-r border-border overflow-hidden">
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto no-scrollbar">
        {navItems.map((item) => {
          if ("children" in item) {
            const isSectionActive =
              location.pathname === "/processed-video" ||
              location.pathname.startsWith("/processed-video/");
            return (
              <div key={item.title} className="space-y-1">
                <NavLink
                  to="/processed-video"
                  end
                  className={`flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${
                    isSectionActive ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-secondary"
                  }`}
                  activeClassName="bg-secondary text-foreground"
                >
                  <item.icon className="w-4 h-4 shrink-0" />
                  <span className="font-mono tracking-wide">{item.title}</span>
                </NavLink>
                {isSectionActive && (
                  <div className="ml-6 space-y-1 border-l border-border pl-3">
                    {item.children.map((child) => (
                      <NavLink
                        key={child.title}
                        to={child.url}
                        end
                        className="block rounded-md px-2 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                        activeClassName="bg-secondary text-foreground"
                      >
                        <span className="font-mono tracking-wide">{child.title}</span>
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            );
          }

          const isActive = location.pathname === item.url;
          return (
            <NavLink
              key={item.title}
              to={item.url}
              end
              className={`flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${
                isActive ? "" : "text-muted-foreground hover:text-foreground hover:bg-secondary"
              }`}
              activeClassName="bg-secondary text-foreground"
            >
              <item.icon className="w-4 h-4 shrink-0" />
              <span className="font-mono tracking-wide">{item.title}</span>
            </NavLink>
          );
        })}
      </nav>

      <div className="px-3 py-4 border-t border-border">
        <p className="text-xs text-muted-foreground px-3 font-mono tracking-wide">© 2026 GROW AI</p>
      </div>
    </aside>);

}
