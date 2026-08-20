import { EXTERNAL_PROVIDER_DISCLOSURE } from "@/lib/externalProviderDisclosure";

export function ExternalProviderDisclosure() {
  const { providers, disclosure, retentionNotice } = EXTERNAL_PROVIDER_DISCLOSURE;

  return (
    <div className="grid gap-4 text-left text-sm text-muted-foreground">
      <div className="grid gap-2">
        <h3 className="font-medium text-foreground">External providers</h3>
        <ul aria-label="External providers" className="flex flex-wrap gap-2">
          {providers.map((provider) => (
            <li
              key={provider}
              className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-foreground"
            >
              {provider}
            </li>
          ))}
        </ul>
      </div>
      <div className="grid gap-2">
        <h3 className="font-medium text-foreground">How data is processed</h3>
        <p>{disclosure}</p>
      </div>
      <div className="grid gap-2">
        <h3 className="font-medium text-foreground">Data retention</h3>
        <p>{retentionNotice}</p>
      </div>
    </div>
  );
}
