import { createHash } from "node:crypto";

export const catalog = [
  {
    id: "headphones",
    name: "Fone Studio",
    category: "Áudio",
    price: 18990,
    icon: "headphones",
    color: "lavender",
  },
  {
    id: "keyboard",
    name: "Teclado Compact",
    category: "Workspace",
    price: 24990,
    icon: "keyboard",
    color: "peach",
  },
  {
    id: "speaker",
    name: "Caixa Pocket",
    category: "Áudio",
    price: 12990,
    icon: "speaker",
    color: "mint",
  },
];
export const scenarios = new Set(["normal", "outage", "slow", "declined"]);

export function payment(body) {
  if (
    !body ||
    typeof body !== "object" ||
    !scenarios.has(body.scenario) ||
    !["probe", "pay", "reconcile"].includes(body.operation)
  ) {
    return [400, { error: "Operação ou cenário de teste inválido." }];
  }
  const common = {
    sandbox: true,
    service: "payment-service",
    scenario: body.scenario,
  };
  if (body.operation === "probe") {
    const healthy = body.scenario !== "outage" && body.scenario !== "slow";
    return [
      healthy ? 200 : 503,
      {
        ...common,
        status: healthy ? "available" : "unavailable",
        operation: "probe",
      },
    ];
  }
  if (
    typeof body.attemptId !== "string" ||
    !/^[a-zA-Z0-9-]{8,100}$/.test(body.attemptId || "") ||
    !Array.isArray(body.items) ||
    body.items.length < 1 ||
    body.items.length > catalog.length
  ) {
    return [400, { error: "Tentativa ou carrinho inválido." }];
  }
  const seen = new Set();
  const items = [];
  for (const item of body.items) {
    if (!item || typeof item !== "object")
      return [400, { error: "Item inválido." }];
    const product = catalog.find((product) => product.id === item.id);
    if (
      !product ||
      seen.has(item.id) ||
      !Number.isInteger(item.quantity) ||
      item.quantity < 1 ||
      item.quantity > 20
    ) {
      return [400, { error: "Produto ou quantidade inválidos." }];
    }
    seen.add(item.id);
    items.push({
      id: product.id,
      quantity: item.quantity,
      unitPrice: product.price,
    });
  }
  items.sort((a, b) => a.id.localeCompare(b.id));
  const total = items.reduce(
    (sum, item) => sum + item.quantity * item.unitPrice,
    0,
  );
  const fingerprint = createHash("sha256")
    .update(JSON.stringify([body.attemptId, items]))
    .digest("hex")
    .slice(0, 20);
  const receipt = {
    ...common,
    attemptId: body.attemptId,
    receiptId: `DEMO-${fingerprint}`,
    items,
    total,
    currency: "BRL",
  };
  if (body.operation === "reconcile") {
    // Only the controlled timeout scenario has an ambiguous success in this sandbox.
    if (body.scenario === "outage")
      return [
        503,
        {
          ...receipt,
          outcome: "unavailable",
          error: "O cenário original não confirmou pagamento.",
        },
      ];
    if (body.scenario === "declined")
      return [
        402,
        {
          ...receipt,
          outcome: "declined",
          error: "Pagamento de teste recusado.",
        },
      ];
    return [200, { ...receipt, outcome: "approved", reconciled: true }];
  }
  if (body.scenario === "outage")
    return [
      503,
      {
        ...receipt,
        outcome: "unavailable",
        error: "Processamento de pagamentos temporariamente indisponível.",
      },
    ];
  if (body.scenario === "slow")
    return [
      504,
      {
        ...receipt,
        outcome: "unknown",
        error:
          "Timeout de teste: consulte esta tentativa antes de tentar novamente.",
      },
    ];
  if (body.scenario === "declined")
    return [
      402,
      {
        ...receipt,
        outcome: "declined",
        error: "Pagamento de teste recusado. O serviço continua disponível.",
      },
    ];
  return [200, { ...receipt, outcome: "approved", reconciled: false }];
}
