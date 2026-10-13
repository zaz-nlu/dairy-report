// 内联 SVG 图形（全部自绘，不依赖任何外部素材）：图标、囚犯头像、牢门、太阳与断链、粉笔正字、印章
window.COMPONENTS = window.COMPONENTS || {};
(function () {
  const C = window.COMPONENTS;
  const INK = '#1a1a1a';

  // ---------- 小图标 ----------
  C.ico = {
    props: { name: String, size: { type: Number, default: 22 } },
    template: `<svg :width="size" :height="size" viewBox="0 0 32 32" fill="none" stroke="#1a1a1a" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <template v-if="name === 'shovel'"><path d="M21 4l7 7"/><path d="M24.5 7.5L14 18"/><path d="M12 14l6 6-2 6c-4 2-10-1-12-7z" fill="#ffd23f"/></template>
      <template v-else-if="name === 'intercom'"><rect x="9" y="9" width="14" height="20" rx="3" fill="#ffd23f"/><path d="M13 4v5M19 3v6"/><path d="M13 15h6M13 19h6M13 23h6"/></template>
      <template v-else-if="name === 'handcuffs'"><circle cx="9" cy="21" r="6" fill="#c9ced6"/><circle cx="23" cy="21" r="6" fill="#c9ced6"/><path d="M12 7h8M9 15V9M23 15V9"/></template>
      <template v-else-if="name === 'trash'"><path d="M6 9h20M12 9V5h8v4M9 9l1.5 18h11L23 9"/><path d="M14 14v8M18 14v8"/></template>
      <template v-else-if="name === 'plus'"><path d="M16 6v20M6 16h20"/></template>
      <template v-else-if="name === 'pen'"><path d="M6 26l2-7L22 5l5 5L13 24z" fill="#ffd23f"/><path d="M19 8l5 5"/></template>
      <template v-else-if="name === 'search'"><circle cx="14" cy="14" r="8" fill="#fff"/><path d="M20 20l8 8"/></template>
      <template v-else-if="name === 'check'"><path d="M5 17l7 7L27 8" stroke-width="4"/></template>
      <template v-else-if="name === 'cross'"><path d="M7 7l18 18M25 7L7 25" stroke-width="4"/></template>
      <template v-else-if="name === 'gear'"><circle cx="16" cy="16" r="5" fill="#ffd23f"/><path d="M16 3v4M16 25v4M3 16h4M25 16h4M7 7l3 3M22 22l3 3M25 7l-3 3M10 22l-3 3"/></template>
      <template v-else-if="name === 'file'"><path d="M8 3h11l6 6v20H8z" fill="#fff"/><path d="M19 3v6h6M12 15h9M12 20h9M12 25h6"/></template>
      <template v-else-if="name === 'door'"><rect x="7" y="4" width="18" height="24" fill="#c9ced6"/><path d="M12 4v24M17 4v24M22 4v24"/></template>
      <template v-else-if="name === 'sun'"><circle cx="16" cy="16" r="6" fill="#ffd23f"/><path d="M16 3v4M16 25v4M3 16h4M25 16h4M7 7l3 3M22 22l3 3M25 7l-3 3M10 22l-3 3"/></template>
      <template v-else-if="name === 'bell'"><path d="M7 23h18l-2-3V13a7 7 0 10-14 0v7z" fill="#ffd23f"/><path d="M13 26a3 3 0 006 0"/></template>
      <template v-else-if="name === 'tray'"><rect x="4" y="6" width="24" height="16" rx="2" fill="#fff"/><path d="M4 26h24M12 22v4M20 22v4"/></template>
      <template v-else-if="name === 'exit'"><path d="M13 5H5v22h8M20 10l6 6-6 6M26 16H11"/></template>
    </svg>`,
  };

  // ---------- 手铐（大，用在装饰和空状态） ----------
  C.handcuffs = {
    props: { size: { type: Number, default: 64 } },
    template: `<svg :width="size" :height="size * 0.62" viewBox="0 0 100 62" fill="none" stroke="#1a1a1a" stroke-width="4" stroke-linejoin="round">
      <ellipse cx="50" cy="12" rx="9" ry="6" fill="#c9ced6"/><ellipse cx="38" cy="14" rx="7" ry="5" fill="#c9ced6"/><ellipse cx="62" cy="14" rx="7" ry="5" fill="#c9ced6"/>
      <rect x="14" y="14" width="20" height="9" rx="2" fill="#c9ced6"/><rect x="66" y="14" width="20" height="9" rx="2" fill="#c9ced6"/>
      <circle cx="24" cy="40" r="17" fill="#c9ced6"/><circle cx="24" cy="40" r="8" fill="#ff7a00"/>
      <circle cx="76" cy="40" r="17" fill="#c9ced6"/><circle cx="76" cy="40" r="8" fill="#ff7a00"/></svg>`,
  };

  // ---------- 囚犯头像：6 种表情 ----------
  // mood: calm 无聊 / sweat 冒汗 / panic 崩溃 / free 放风 / done 得意 / sad 沮丧 / blank 懵
  C.prisoner = {
    props: { mood: { type: String, default: 'calm' }, size: { type: Number, default: 92 } },
    template: `<svg :width="size" :height="size" viewBox="0 0 120 120" class="prisoner" :class="'m-' + mood" fill="none" stroke="#1a1a1a" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">
      <defs><clipPath id="pv-body"><path d="M8 120Q12 86 60 82Q108 86 112 120Z"/></clipPath><clipPath id="pv-cap"><path d="M30 40Q30 8 60 8Q90 8 90 40Z"/></clipPath></defs>
      <path d="M8 120Q12 86 60 82Q108 86 112 120Z" fill="#fff"/>
      <g clip-path="url(#pv-body)" stroke-width="7"><path d="M0 94H120M0 106H120M0 118H120"/></g>
      <path d="M8 120Q12 86 60 82Q108 86 112 120Z"/>
      <rect x="50" y="68" width="20" height="16" fill="#f6d3a2"/>
      <circle cx="60" cy="46" r="29" fill="#f6d3a2"/>
      <path d="M30 40Q30 8 60 8Q90 8 90 40Z" fill="#fff"/>
      <g clip-path="url(#pv-cap)" stroke-width="6"><path d="M38 0V50M54 0V50M70 0V50M86 0V50"/></g>
      <path d="M30 40Q30 8 60 8Q90 8 90 40Z"/><path d="M28 40H92" stroke-width="5"/>
      <!-- 脸 -->
      <template v-if="mood === 'calm'"><path d="M44 52h10M66 52h10" /><path d="M48 66h24" /><path d="M43 46l12 2M65 48l12-2" stroke-width="2.5"/></template>
      <template v-else-if="mood === 'sweat'"><circle cx="49" cy="52" r="3.2" fill="#1a1a1a"/><circle cx="71" cy="52" r="3.2" fill="#1a1a1a"/><path d="M42 44l14-3M64 41l14 3" stroke-width="2.5"/><path d="M48 68q6-5 12 0t12 0"/>
        <path d="M88 44q4 7 0 10q-4-3 0-10z" fill="#7fd1ff" stroke-width="2.5"/></template>
      <template v-else-if="mood === 'panic'"><circle cx="48" cy="52" r="6.5" fill="#fff"/><circle cx="72" cy="52" r="6.5" fill="#fff"/><circle cx="48" cy="53" r="2.4" fill="#1a1a1a"/><circle cx="72" cy="53" r="2.4" fill="#1a1a1a"/>
        <path d="M40 41l14 4M80 41l-14 4" stroke-width="3"/><ellipse cx="60" cy="71" rx="7" ry="6" fill="#d7263d"/>
        <path d="M90 40q4 7 0 10q-4-3 0-10zM28 46q4 7 0 10q-4-3 0-10z" fill="#7fd1ff" stroke-width="2.5"/></template>
      <template v-else-if="mood === 'free' || mood === 'done'"><path d="M42 54q6-8 12 0M66 54q6-8 12 0" stroke-width="3.5"/><path d="M44 63q16 16 32 0z" fill="#fff"/><circle cx="43" cy="63" r="4" fill="#ff9aa8" stroke="none"/><circle cx="77" cy="63" r="4" fill="#ff9aa8" stroke="none"/></template>
      <template v-else-if="mood === 'sad'"><circle cx="49" cy="53" r="3" fill="#1a1a1a"/><circle cx="71" cy="53" r="3" fill="#1a1a1a"/><path d="M42 45l12 5M78 45l-12 5" stroke-width="2.5"/><path d="M48 72q12-10 24 0"/><path d="M49 58q-3 8 0 10q3-2 0-10z" fill="#7fd1ff" stroke-width="2.2"/></template>
      <template v-else><circle cx="49" cy="52" r="3.2" fill="#1a1a1a"/><circle cx="71" cy="52" r="3.2" fill="#1a1a1a"/><path d="M50 68q10 4 20-2"/><text x="82" y="38" font-size="22" stroke="none" fill="#1a1a1a" font-family="ZCool, sans-serif">?</text></template>
    </svg>`,
  };

  // ---------- 牢门：open 时门扇转开 ----------
  C.celldoor = {
    props: { open: Boolean, size: { type: Number, default: 84 } },
    template: `<svg :width="size" :height="size * 1.15" viewBox="0 0 100 115" class="celldoor" :class="{ open }" fill="none" stroke="#1a1a1a" stroke-width="4" stroke-linejoin="round">
      <rect x="8" y="8" width="84" height="104" fill="#3a3a3a"/>
      <g v-if="open" fill="#ffd23f" stroke="none"><circle cx="64" cy="58" r="20" opacity=".9"/><path d="M30 112l20-30 20 30z" opacity=".5"/></g>
      <g class="door-leaf"><rect x="8" y="8" width="84" height="104" fill="#c9ced6"/>
        <path d="M24 8v104M42 8v104M60 8v104M78 8v104" stroke-width="5"/><path d="M8 40H92M8 80H92" stroke-width="5"/>
        <circle cx="70" cy="62" r="4" fill="#ffd23f"/></g>
      <rect x="8" y="8" width="84" height="104"/></svg>`,
  };

  // ---------- 太阳 + 断掉的锁链（放风日） ----------
  C.sunchain = {
    props: { size: { type: Number, default: 92 } },
    template: `<svg :width="size" :height="size" viewBox="0 0 120 120" class="sunchain" fill="none" stroke="#1a1a1a" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">
      <g class="rays"><path d="M60 8v14M60 98v14M8 60h14M98 60h14M23 23l10 10M87 87l10 10M97 23L87 33M33 87L23 97"/></g>
      <circle cx="60" cy="60" r="26" fill="#ffd23f"/><path d="M50 57q4-5 8 0M64 57q4-5 8 0" stroke-width="3"/><path d="M50 68q10 9 20 0" stroke-width="3"/>
      <g fill="#c9ced6"><ellipse cx="18" cy="104" rx="11" ry="6" transform="rotate(-20 18 104)"/><ellipse cx="38" cy="110" rx="11" ry="6" transform="rotate(10 38 110)"/>
        <path d="M70 108l8-6M80 110l6 4M92 104l8-4" stroke-width="3"/></g></svg>`,
  };

  // ---------- 粉笔正字：每 5 天画满一个「正」（5 笔：上横、中竖、中短横、左竖、下横），不足 5 的画前几笔 ----------
  C.tally = {
    props: { n: { type: Number, default: 0 } },
    data: () => ({ strokes: ['M4 8H40', 'M22 8V42', 'M22 24H36', 'M10 24V42', 'M4 42H40'] }),
    computed: {
      groups() { const g = [], full = Math.floor(this.n / 5); for (let i = 0; i < Math.min(full, 6); i++) g.push(5); if (this.n % 5) g.push(this.n % 5); return g; },
      more() { return Math.max(0, Math.floor(this.n / 5) - 6); },
    },
    template: `<span class="tally" :title="n + '天'"><svg v-for="(k, gi) in groups" :key="gi" class="tg" width="42" height="48" viewBox="0 0 44 50" fill="none" stroke="#f4f4f4" stroke-width="3.2" stroke-linecap="round" :style="{ transform: 'rotate(' + (gi % 2 ? 2 : -2) + 'deg)' }"><path v-for="i in k" :key="i" :d="strokes[i - 1]"/></svg><span v-if="more" class="tally-more">×{{ more }}</span><span v-if="!n" class="tally-empty">——</span></span>`,
  };

  // ---------- 印章 ----------
  C.stamp = {
    props: { tone: { type: String, default: 'red' }, tilt: { type: Number, default: -6 } },
    template: `<span class="stamp" :class="'t-' + tone" :style="{ transform: 'rotate(' + tilt + 'deg)' }"><slot/></span>`,
  };
})();
