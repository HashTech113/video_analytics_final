import { Menu } from "lucide-react";
import { Button } from "@/components/ui/button";
import growLogo from "@/assets/grow_logo_black.png";
import { useEffect, useState } from "react";

interface TopNavbarProps {
  onToggleSidebar?: () => void;
}

export function TopNavbar({ onToggleSidebar }: TopNavbarProps) {
  const messages = [
    "Video Analytics Platform",
    "Your camera see. Our AI understands",
  ];
  const [messageIndex, setMessageIndex] = useState(0);
  const [isVisible, setIsVisible] = useState(true);

  useEffect(() => {
    let fadeTimeout: ReturnType<typeof setTimeout> | null = null;
    const interval = setInterval(() => {
      setIsVisible(false);
      fadeTimeout = setTimeout(() => {
        setMessageIndex((prev) => (prev + 1) % messages.length);
        setIsVisible(true);
      }, 500);
    }, 3600);

    return () => {
      clearInterval(interval);
      if (fadeTimeout) clearTimeout(fadeTimeout);
    };
  }, [messages.length]);

  return (
    <header className="relative h-14 border-b border-border bg-card flex items-center px-4 md:px-6 shrink-0">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          onClick={onToggleSidebar}
        >
          <Menu className="w-5 h-5" />
        </Button>

        <div className="flex items-center">
          <img src={growLogo} alt="OwlYtics" className="h-8 w-auto object-contain" />
        </div>
      </div>

      <div className="absolute left-1/2 -translate-x-1/2 text-center leading-tight w-[72%] sm:w-auto">
        <p
          className={`text-lg md:text-xl font-semibold tracking-widest text-white transition-all duration-700 ${
            isVisible ? "opacity-100 translate-y-0" : "opacity-0 -translate-y-1"
          }`}
          style={{ fontFamily: "'Times New Roman', Times, serif" }}
        >
          {messages[messageIndex]}
        </p>
      </div>
    </header>
  );
}
