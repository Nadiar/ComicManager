<script setup>
import DefaultTheme from "vitepress/theme";
import { onMounted } from "vue";
import { useRouter } from "vitepress";
import GLightbox from "glightbox";
import "glightbox/dist/css/glightbox.css";

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
  <Layout />
</template>

<style>
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
