import { HeroSection } from "@/components/home/hero-section";
import { UsernameInput } from "@/components/home/username-input";
import { RecentJobsBanner } from "@/components/home/recent-jobs-banner";

export default function HomePage() {
  return (
    <div className="gradient-bg flex min-h-dvh flex-col items-center justify-center px-4 pt-14">
      <div className="mx-auto flex w-full max-w-lg flex-col items-center gap-8 py-16">
        <HeroSection />
        <UsernameInput />
        <RecentJobsBanner />
      </div>
    </div>
  );
}
