export function IconDefinitions() {
  return (
    <svg className="defs" aria-hidden="true"><defs>
      <symbol id="i-fork" viewBox="0 0 42 42"><rect width="42" height="42" rx="8" fill="#e3e4e0"/><g fill="none" stroke="#292a2b" strokeLinecap="round" strokeWidth="3.3"><path d="M11 10v9c0 8 13 8 13 0v-9M17.5 25v8m1-23v8M29 10v13"/></g></symbol>
      <symbol id="i-dict" viewBox="0 0 24 24"><rect x="8" y="2" width="8" height="13" rx="4"/><path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v4m-4 0h8"/></symbol>
      <symbol id="i-file" viewBox="0 0 24 24"><path d="M5 3h9l5 5v13H5zM14 3v6h5M8 15h2l1-2 2 4 1-2h2"/></symbol>
      <symbol id="i-compare" viewBox="0 0 24 24"><path d="M3 6h12m-3-3 3 3-3 3M21 18H9m3-3-3 3 3 3M4 12h4m8 0h4"/></symbol>
      <symbol id="i-models" viewBox="0 0 24 24"><path d="m3 8 9-5 9 5-9 5zM3 12l9 5 9-5m-18 4 9 5 9-5"/></symbol>
      <symbol id="i-settings" viewBox="0 0 24 24"><path d="M4 6h6m4 0h6M4 12h10m4 0h2M4 18h2m4 0h10"/><circle cx="12" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="8" cy="18" r="2"/></symbol>
      <symbol id="i-gloss" viewBox="0 0 24 24"><path d="M3 4q5-2 9 1 4-3 9-1v15q-5-2-9 1-4-3-9-1zM12 5v15"/></symbol>
      <symbol id="i-status" viewBox="0 0 24 24"><path d="M2 12h5l3-7 4 14 3-7h5"/></symbol>
      <symbol id="i-log" viewBox="0 0 24 24"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8m-8 4h8m-8 4h5"/></symbol>
      <symbol id="i-api" viewBox="0 0 24 24"><path d="m7 7-5 5 5 5m10-10 5 5-5 5m-3-14-4 18"/></symbol>
      <symbol id="i-text" viewBox="0 0 24 24"><path d="M4 5h16M4 10h16M4 15h10m-10 5h13"/></symbol>
      <symbol id="i-copy" viewBox="0 0 24 24"><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/></symbol>
      <symbol id="i-stop" viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" rx="2"/></symbol>
      <symbol id="i-arrow" viewBox="0 0 24 24"><path d="M4 12h15m-6-6 6 6-6 6"/></symbol>
      <symbol id="i-ext" viewBox="0 0 24 24"><path d="M14 3h7v7m0-7L10 14m0-9H4v15h15v-6"/></symbol>
      <symbol id="i-folder" viewBox="0 0 24 24"><path d="M3 6h6l2 2h10v12H3z"/></symbol>
    </defs></svg>
  )
}

export function Icon({ name, className = "ico" }) {
  return <svg className={className} aria-hidden="true"><use href={"#i-" + name} /></svg>
}
