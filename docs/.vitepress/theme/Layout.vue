<script setup>
import DefaultTheme from "vitepress/theme";
import { onMounted } from "vue";
import { useRouter } from "vitepress";
import GLightbox from "glightbox";
import "glightbox/dist/css/glightbox.css";
import ComicHero from "./ComicHero.vue";

const { Layout } = DefaultTheme;
const router = useRouter();

let lightbox = null;

const setupLightbox = () => {
  if (lightbox) lightbox.destroy();
  lightbox = GLightbox({
    selector: "[data-zoomable]",
    touchNavigation: true,
    loop: false,
  });
};

onMounted(() => {
  setupLightbox();
  router.onAfterRouteChange = setupLightbox;
});
</script>

<template>
  <Layout>
    <template #home-hero-image>
      <ComicHero />
    </template>
  </Layout>
</template>

<style>
/* Comic-flavored hero branding */
:root {
  --vp-home-hero-name-color: transparent;
  --vp-home-hero-name-background: linear-gradient(115deg, #f6a623 25%, #ff5a45 85%);
  --vp-home-hero-image-background-image: radial-gradient(circle, rgba(246, 166, 35, 0.5), rgba(255, 90, 69, 0.25));
  --vp-home-hero-image-filter: blur(60px);
}

/* Page-load entrance: name slams down like a stamp, the rest rises in */
@media (prefers-reduced-motion: no-preference) {
  .VPHome .VPHero .name {
    animation: cm-hero-slam 0.7s cubic-bezier(0.25, 1.2, 0.45, 1) 0.05s backwards;
  }

  .VPHome .VPHero .text {
    animation: cm-hero-rise 0.7s ease-out 0.3s backwards;
  }

  .VPHome .VPHero .tagline {
    animation: cm-hero-rise 0.7s ease-out 0.45s backwards;
  }

  .VPHome .VPHero .actions {
    animation: cm-hero-rise 0.7s ease-out 0.6s backwards;
  }

  .VPHome .VPFeatures .item {
    animation: cm-hero-rise 0.75s ease-out backwards;
  }

  .VPHome .VPFeatures .item:nth-child(1) {
    animation-delay: 0.75s;
  }

  .VPHome .VPFeatures .item:nth-child(2) {
    animation-delay: 0.87s;
  }

  .VPHome .VPFeatures .item:nth-child(3) {
    animation-delay: 0.99s;
  }
}

@keyframes cm-hero-slam {
  0% {
    opacity: 0;
    transform: scale(1.8) rotate(-3deg);
  }

  40% {
    opacity: 1;
  }

  65% {
    transform: scale(0.97) rotate(1deg);
  }

  100% {
    opacity: 1;
    transform: scale(1) rotate(0deg);
  }
}

@keyframes cm-hero-rise {
  from {
    opacity: 0;
    transform: translateY(12px);
  }

  to {
    opacity: 1;
    transform: none;
  }
}

.vp-doc p:has(img) {
  text-align: center;
}

.vp-doc .img-caption {
  display: block;
  font-size: 0.85rem;
  color: var(--vp-c-text-2);
  margin-top: 0.5rem;
  font-style: italic;
  text-align: center;
}

/* GLightbox caption overrides */
.gslide-description {
  background: rgba(0, 0, 0, 0.6) !important;
  backdrop-filter: blur(8px);
  padding: 0.4rem 1rem !important;
}

.gdesc-inner {
  padding: 0.3rem 0 !important;
}

.gslide-title {
  font-size: 0.8rem !important;
  font-weight: 400 !important;
  font-style: italic;
  color: rgba(255, 255, 255, 0.75) !important;
  margin: 0 !important;
  text-align: center;
}
</style>
