<template>
  <div class="comic-hero" aria-hidden="true">
    <svg viewBox="0 0 480 460" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <!-- 12-point action burst, hand-drawn jitter -->
        <polygon
          id="ch-burst-shape"
          points="445,220 383,258 406,316 340,320 344,400 278,361 240,418 201,365 145,385 138,322 58,325 98,258 45,220 102,183 62,117 135,115 143,53 202,80 240,13 277,81 338,50 345,115 415,119 381,182"
        />
        <!-- small 8-point burst for the word chips -->
        <polygon
          id="ch-chip-shape"
          points="42,0 24,10 27,27 10,25 0,41 -10,23 -28,28 -25,10 -40,0 -24,-10 -30,-30 -9,-23 0,-39 10,-25 28,-28 24,-11"
        />
        <path id="ch-sparkle" d="M0,-14 L4,-4 L14,0 L4,4 L0,14 L-4,4 L-14,0 L-4,-4 Z" />
        <pattern id="ch-halftone" width="14" height="14" patternUnits="userSpaceOnUse">
          <circle cx="3" cy="3" r="1.6" fill="#5C4A32" opacity="0.18" />
          <circle cx="10" cy="10" r="1.6" fill="#5C4A32" opacity="0.18" />
        </pattern>
      </defs>

      <!-- speed lines radiating outward -->
      <g class="ch-speedlines">
        <line x1="438" y1="278" x2="467" y2="286" />
        <line x1="372" y1="382" x2="391" y2="405" />
        <line x1="222" y1="429" x2="220" y2="452" />
        <line x1="108" y1="382" x2="89" y2="405" />
        <line x1="42" y1="278" x2="13" y2="286" />
        <line x1="47" y1="155" x2="19" y2="145" />
        <line x1="122" y1="57" x2="105" y2="33" />
        <line x1="240" y1="20" x2="240" y2="3" />
        <line x1="358" y1="57" x2="375" y2="33" />
        <line x1="433" y1="155" x2="461" y2="145" />
      </g>

      <g class="ch-float">
        <!-- burst with offset comic shadow -->
        <g class="ch-burst">
          <use href="#ch-burst-shape" transform="translate(8 10)" fill="#5C4A32" opacity="0.22" />
          <use href="#ch-burst-shape" fill="#FFC83D" stroke="#5C4A32" stroke-width="7" stroke-linejoin="round" />
          <use href="#ch-burst-shape" fill="url(#ch-halftone)" />
        </g>

        <!-- gear peeking out top-right, slow spin -->
        <g transform="translate(360 108)">
          <g class="ch-gear">
            <g fill="#2E6FAE" stroke="#5C4A32" stroke-width="5">
              <rect x="-9" y="-54" width="18" height="22" rx="4" />
              <rect x="-9" y="32" width="18" height="22" rx="4" />
              <rect x="-54" y="-9" width="22" height="18" rx="4" />
              <rect x="32" y="-9" width="22" height="18" rx="4" />
              <rect x="-9" y="-54" width="18" height="22" rx="4" transform="rotate(45)" />
              <rect x="-9" y="32" width="18" height="22" rx="4" transform="rotate(45)" />
              <rect x="-54" y="-9" width="22" height="18" rx="4" transform="rotate(45)" />
              <rect x="32" y="-9" width="22" height="18" rx="4" transform="rotate(45)" />
            </g>
            <circle r="38" fill="#2E6FAE" stroke="#5C4A32" stroke-width="6" />
            <circle r="15" fill="#FFC83D" stroke="#5C4A32" stroke-width="6" />
          </g>
        </g>

        <!-- stack of comics -->
        <g class="ch-stack">
          <rect x="170" y="115" width="145" height="215" rx="10" transform="rotate(-10 242 222)" fill="#D9822B" stroke="#5C4A32" stroke-width="7" />
          <rect x="170" y="115" width="145" height="215" rx="10" transform="rotate(6 242 222)" fill="#E8A33D" stroke="#5C4A32" stroke-width="7" />

          <!-- front comic cover -->
          <g>
            <rect x="170" y="115" width="145" height="215" rx="10" fill="#F7D154" />
            <rect x="170" y="115" width="22" height="215" rx="10" fill="#2E6FAE" />
            <rect x="182" y="115" width="10" height="215" fill="#2E6FAE" />
            <!-- title box -->
            <rect x="202" y="130" width="101" height="28" rx="5" fill="#FFF3D6" stroke="#5C4A32" stroke-width="4" />
            <rect x="212" y="140" width="56" height="8" rx="4" fill="#5C4A32" />
            <!-- panel row -->
            <rect x="202" y="170" width="47" height="60" rx="5" fill="#FFF3D6" stroke="#5C4A32" stroke-width="4" />
            <rect x="256" y="170" width="47" height="60" rx="5" fill="#FFF3D6" stroke="#5C4A32" stroke-width="4" />
            <!-- wide panel -->
            <rect x="202" y="242" width="101" height="46" rx="5" fill="#FFF3D6" stroke="#5C4A32" stroke-width="4" />
            <rect x="212" y="300" width="70" height="8" rx="4" fill="#5C4A32" opacity="0.55" />
            <rect x="212" y="314" width="44" height="8" rx="4" fill="#5C4A32" opacity="0.35" />
            <!-- speech bubble in right panel -->
            <g>
              <ellipse cx="280" cy="194" rx="15" ry="13" fill="#FFFFFF" stroke="#5C4A32" stroke-width="4" />
              <path d="M272 204 L266 216 L280 207 Z" fill="#FFFFFF" stroke="#5C4A32" stroke-width="3" stroke-linejoin="round" />
              <text x="280" y="196" class="ch-bang" text-anchor="middle" dominant-baseline="central">!</text>
            </g>
            <!-- check mark in left panel: tagged and done -->
            <path d="M212 200 L222 212 L240 184" fill="none" stroke="#3E8E55" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" />
            <rect x="170" y="115" width="145" height="215" rx="10" fill="none" stroke="#5C4A32" stroke-width="7" />
          </g>
        </g>

        <!-- action word chips -->
        <g transform="translate(72 74) rotate(-12)">
          <g class="ch-chip ch-chip-1">
            <use href="#ch-chip-shape" transform="scale(1.5 1.2)" fill="#FF6B4A" stroke="#5C4A32" stroke-width="4" stroke-linejoin="round" />
            <text class="ch-word ch-word-sm" fill="#FFF8E7" text-anchor="middle" dominant-baseline="central">SCRAPE!</text>
          </g>
        </g>
        <g transform="translate(420 320) rotate(10)">
          <g class="ch-chip ch-chip-2">
            <use href="#ch-chip-shape" transform="scale(1.1)" fill="#2E6FAE" stroke="#5C4A32" stroke-width="4" stroke-linejoin="round" />
            <text class="ch-word" fill="#FFF8E7" text-anchor="middle" dominant-baseline="central">TAG!</text>
          </g>
        </g>
        <g transform="translate(88 386) rotate(-8)">
          <g class="ch-chip ch-chip-3">
            <use href="#ch-chip-shape" transform="scale(1.5 1.2)" fill="#FFE08A" stroke="#5C4A32" stroke-width="4" stroke-linejoin="round" />
            <text class="ch-word ch-word-sm" fill="#FFF8E7" text-anchor="middle" dominant-baseline="central">FORMAT!</text>
          </g>
        </g>

        <!-- sparkles -->
        <g transform="translate(160 28)">
          <use href="#ch-sparkle" class="ch-twinkle ch-twinkle-1" fill="#E8A33D" />
        </g>
        <g transform="translate(404 56)">
          <use href="#ch-sparkle" class="ch-twinkle ch-twinkle-2" fill="#FF6B4A" />
        </g>
        <g transform="translate(438 392)">
          <use href="#ch-sparkle" class="ch-twinkle ch-twinkle-3" fill="#E8A33D" />
        </g>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.comic-hero {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.comic-hero svg {
  width: 100%;
  height: 100%;
  max-width: 400px;
  overflow: visible;
}

.ch-speedlines line {
  stroke: var(--vp-c-text-3);
  stroke-width: 5;
  stroke-linecap: round;
  opacity: 0.5;
}

.ch-word {
  font-family: "Arial Black", "Avenir Heavy", "Inter", sans-serif;
  font-size: 19px;
  font-weight: 900;
  font-style: italic;
  letter-spacing: 0.5px;
  paint-order: stroke;
  stroke: #5c4a32;
  stroke-width: 3px;
}

.ch-word-sm {
  font-size: 13.5px;
  letter-spacing: 0;
}

.ch-bang {
  font-family: "Arial Black", "Avenir Heavy", "Inter", sans-serif;
  font-size: 17px;
  font-weight: 900;
  fill: #5c4a32;
}

/* animated groups pivot around their own bounding box */
.ch-burst,
.ch-stack,
.ch-gear,
.ch-chip,
.ch-twinkle,
.ch-float,
.ch-speedlines {
  transform-box: fill-box;
  transform-origin: center;
}

@media (prefers-reduced-motion: no-preference) {
  .ch-burst {
    animation: ch-slam 0.8s cubic-bezier(0.25, 1.3, 0.45, 1) 0.05s backwards;
  }

  .ch-stack {
    animation: ch-slam 0.75s cubic-bezier(0.25, 1.3, 0.45, 1) 0.3s backwards;
  }

  .ch-speedlines {
    animation: ch-lines 1.2s ease-out 0.1s backwards;
  }

  .ch-gear {
    animation:
      ch-pop 0.5s cubic-bezier(0.2, 1.6, 0.4, 1) 0.5s backwards,
      ch-spin 24s linear 1s infinite;
  }

  .ch-chip-1 {
    animation:
      ch-pop 0.45s cubic-bezier(0.2, 1.8, 0.4, 1) 0.75s backwards,
      ch-wiggle 3.2s ease-in-out 1.3s infinite alternate;
  }

  .ch-chip-2 {
    animation:
      ch-pop 0.45s cubic-bezier(0.2, 1.8, 0.4, 1) 0.9s backwards,
      ch-wiggle 2.7s ease-in-out 1.5s infinite alternate-reverse;
  }

  .ch-chip-3 {
    animation:
      ch-pop 0.45s cubic-bezier(0.2, 1.8, 0.4, 1) 1.05s backwards,
      ch-wiggle 3.6s ease-in-out 1.6s infinite alternate;
  }

  .ch-twinkle {
    animation: ch-twinkle 2.4s ease-in-out infinite;
  }

  .ch-twinkle-1 {
    animation-delay: 1.2s;
  }

  .ch-twinkle-2 {
    animation-delay: 1.7s;
  }

  .ch-twinkle-3 {
    animation-delay: 2.1s;
  }

  .ch-float {
    animation: ch-bob 5s ease-in-out 1.6s infinite alternate;
  }
}

@keyframes ch-slam {
  0% {
    opacity: 0;
    transform: scale(0.2) rotate(-25deg);
  }

  35% {
    opacity: 1;
  }

  70% {
    transform: scale(1.06) rotate(2deg);
  }

  100% {
    opacity: 1;
    transform: scale(1) rotate(0deg);
  }
}

@keyframes ch-pop {
  0% {
    opacity: 0;
    transform: scale(0.3);
  }

  40% {
    opacity: 1;
  }

  70% {
    transform: scale(1.18);
  }

  100% {
    opacity: 1;
    transform: scale(1);
  }
}

@keyframes ch-lines {
  0% {
    opacity: 0;
    transform: scale(0.75);
  }

  60% {
    opacity: 0.7;
  }

  100% {
    opacity: 0.5;
    transform: scale(1);
  }
}

@keyframes ch-spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes ch-wiggle {
  from {
    transform: rotate(-4deg);
  }

  to {
    transform: rotate(4deg);
  }
}

@keyframes ch-twinkle {
  0%,
  100% {
    opacity: 0.25;
    transform: scale(0.6) rotate(0deg);
  }

  50% {
    opacity: 1;
    transform: scale(1.15) rotate(45deg);
  }
}

@keyframes ch-bob {
  from {
    transform: translateY(-5px);
  }

  to {
    transform: translateY(6px);
  }
}
</style>
