var __StripeExtExports = (() => {
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

  // .build/manifest.js
  var manifest_exports = {};
  __export(manifest_exports, {
    BUILD_TIME: () => BUILD_TIME,
    default: () => manifest_default
  });
  var BUILD_TIME = "2026-10-14 22:15:55.382948 -0400 EDT m=+5.248254918";
  var manifest_default = {
    "$schema": "https://stripe.com/stripe-app.schema.json",
    "allowed_redirect_uris": [
      "https://localhost:5173/api/stripe/callback",
      "https://stoke-y4sf.onrender.com/api/stripe/callback"
    ],
    "distribution_type": "public",
    "icon": "./icon.png",
    "id": "com.stoke.stoke",
    "name": "Stoke",
    "permissions": [
      {
        "permission": "payment_intent_read",
        "purpose": "Shows your payments and who made them, so Stoke can tell you who to thank."
      },
      {
        "permission": "charge_read",
        "purpose": "Reads each payment's charge and refunds, to show what you actually took home."
      },
      {
        "permission": "dispute_read",
        "purpose": "Shows disputed payments that are waiting on your response."
      },
      {
        "permission": "invoice_read",
        "purpose": "Reads subscription invoices for plan names and failed renewals."
      },
      {
        "permission": "subscription_read",
        "purpose": "Shows your paid subscribers, renewals and cancellations."
      },
      {
        "permission": "customer_read",
        "purpose": "Shows who your subscribers and customers are, so you can reach out to them."
      },
      {
        "permission": "balance_transaction_source_read",
        "purpose": "Reads the fees on each payment, to show what reached your balance."
      },
      {
        "permission": "event_read",
        "purpose": "Keeps Stoke up to date as payments and subscriptions change."
      },
      {
        "permission": "connected_account_read",
        "purpose": "Shows your account's name and payout currency in Stoke."
      }
    ],
    "stripe_api_access_type": "oauth",
    "version": "0.0.1"
  };
  return __toCommonJS(manifest_exports);
})();
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsibWFuaWZlc3QuanMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbIi8vIEFVVE9HRU5FUkFURUQgLSBETyBOT1QgTU9ESUZZXG5cbi8vIFRpbWVzdGFtcCBjaGFuZ2VzIG9uIGV2ZXJ5IGV4cG9ydCwgZW5zdXJpbmcgdGhlIGRldiBzZXJ2ZXIgZGV0ZWN0cyBhIHJlYnVpbGRcbmV4cG9ydCBjb25zdCBCVUlMRF9USU1FID0gJzIwMjYtMTAtMTQgMjI6MTU6NTUuMzgyOTQ4IC0wNDAwIEVEVCBtPSs1LjI0ODI1NDkxOCc7XG5cbi8vIEFwcCBtYW5pZmVzdCBcdTIwMTQgY29uc3VtZWQgYnkgdGhlIERhc2hib2FyZCB0byBjb25maWd1cmUgdGhlIGFwcFxuZXhwb3J0IGRlZmF1bHQge1xuICBcIiRzY2hlbWFcIjogXCJodHRwczovL3N0cmlwZS5jb20vc3RyaXBlLWFwcC5zY2hlbWEuanNvblwiLFxuICBcImFsbG93ZWRfcmVkaXJlY3RfdXJpc1wiOiBbXG4gICAgXCJodHRwczovL2xvY2FsaG9zdDo1MTczL2FwaS9zdHJpcGUvY2FsbGJhY2tcIixcbiAgICBcImh0dHBzOi8vc3Rva2UteTRzZi5vbnJlbmRlci5jb20vYXBpL3N0cmlwZS9jYWxsYmFja1wiXG4gIF0sXG4gIFwiZGlzdHJpYnV0aW9uX3R5cGVcIjogXCJwdWJsaWNcIixcbiAgXCJpY29uXCI6IFwiLi9pY29uLnBuZ1wiLFxuICBcImlkXCI6IFwiY29tLnN0b2tlLnN0b2tlXCIsXG4gIFwibmFtZVwiOiBcIlN0b2tlXCIsXG4gIFwicGVybWlzc2lvbnNcIjogW1xuICAgIHtcbiAgICAgIFwicGVybWlzc2lvblwiOiBcInBheW1lbnRfaW50ZW50X3JlYWRcIixcbiAgICAgIFwicHVycG9zZVwiOiBcIlNob3dzIHlvdXIgcGF5bWVudHMgYW5kIHdobyBtYWRlIHRoZW0sIHNvIFN0b2tlIGNhbiB0ZWxsIHlvdSB3aG8gdG8gdGhhbmsuXCJcbiAgICB9LFxuICAgIHtcbiAgICAgIFwicGVybWlzc2lvblwiOiBcImNoYXJnZV9yZWFkXCIsXG4gICAgICBcInB1cnBvc2VcIjogXCJSZWFkcyBlYWNoIHBheW1lbnQncyBjaGFyZ2UgYW5kIHJlZnVuZHMsIHRvIHNob3cgd2hhdCB5b3UgYWN0dWFsbHkgdG9vayBob21lLlwiXG4gICAgfSxcbiAgICB7XG4gICAgICBcInBlcm1pc3Npb25cIjogXCJkaXNwdXRlX3JlYWRcIixcbiAgICAgIFwicHVycG9zZVwiOiBcIlNob3dzIGRpc3B1dGVkIHBheW1lbnRzIHRoYXQgYXJlIHdhaXRpbmcgb24geW91ciByZXNwb25zZS5cIlxuICAgIH0sXG4gICAge1xuICAgICAgXCJwZXJtaXNzaW9uXCI6IFwiaW52b2ljZV9yZWFkXCIsXG4gICAgICBcInB1cnBvc2VcIjogXCJSZWFkcyBzdWJzY3JpcHRpb24gaW52b2ljZXMgZm9yIHBsYW4gbmFtZXMgYW5kIGZhaWxlZCByZW5ld2Fscy5cIlxuICAgIH0sXG4gICAge1xuICAgICAgXCJwZXJtaXNzaW9uXCI6IFwic3Vic2NyaXB0aW9uX3JlYWRcIixcbiAgICAgIFwicHVycG9zZVwiOiBcIlNob3dzIHlvdXIgcGFpZCBzdWJzY3JpYmVycywgcmVuZXdhbHMgYW5kIGNhbmNlbGxhdGlvbnMuXCJcbiAgICB9LFxuICAgIHtcbiAgICAgIFwicGVybWlzc2lvblwiOiBcImN1c3RvbWVyX3JlYWRcIixcbiAgICAgIFwicHVycG9zZVwiOiBcIlNob3dzIHdobyB5b3VyIHN1YnNjcmliZXJzIGFuZCBjdXN0b21lcnMgYXJlLCBzbyB5b3UgY2FuIHJlYWNoIG91dCB0byB0aGVtLlwiXG4gICAgfSxcbiAgICB7XG4gICAgICBcInBlcm1pc3Npb25cIjogXCJiYWxhbmNlX3RyYW5zYWN0aW9uX3NvdXJjZV9yZWFkXCIsXG4gICAgICBcInB1cnBvc2VcIjogXCJSZWFkcyB0aGUgZmVlcyBvbiBlYWNoIHBheW1lbnQsIHRvIHNob3cgd2hhdCByZWFjaGVkIHlvdXIgYmFsYW5jZS5cIlxuICAgIH0sXG4gICAge1xuICAgICAgXCJwZXJtaXNzaW9uXCI6IFwiZXZlbnRfcmVhZFwiLFxuICAgICAgXCJwdXJwb3NlXCI6IFwiS2VlcHMgU3Rva2UgdXAgdG8gZGF0ZSBhcyBwYXltZW50cyBhbmQgc3Vic2NyaXB0aW9ucyBjaGFuZ2UuXCJcbiAgICB9LFxuICAgIHtcbiAgICAgIFwicGVybWlzc2lvblwiOiBcImNvbm5lY3RlZF9hY2NvdW50X3JlYWRcIixcbiAgICAgIFwicHVycG9zZVwiOiBcIlNob3dzIHlvdXIgYWNjb3VudCdzIG5hbWUgYW5kIHBheW91dCBjdXJyZW5jeSBpbiBTdG9rZS5cIlxuICAgIH1cbiAgXSxcbiAgXCJzdHJpcGVfYXBpX2FjY2Vzc190eXBlXCI6IFwib2F1dGhcIixcbiAgXCJ2ZXJzaW9uXCI6IFwiMC4wLjFcIlxufTtcbiJdLAogICJtYXBwaW5ncyI6ICI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7O0FBQUE7QUFBQTtBQUFBO0FBQUE7QUFBQTtBQUdPLE1BQU0sYUFBYTtBQUcxQixNQUFPLG1CQUFRO0FBQUEsSUFDYixXQUFXO0FBQUEsSUFDWCx5QkFBeUI7QUFBQSxNQUN2QjtBQUFBLE1BQ0E7QUFBQSxJQUNGO0FBQUEsSUFDQSxxQkFBcUI7QUFBQSxJQUNyQixRQUFRO0FBQUEsSUFDUixNQUFNO0FBQUEsSUFDTixRQUFRO0FBQUEsSUFDUixlQUFlO0FBQUEsTUFDYjtBQUFBLFFBQ0UsY0FBYztBQUFBLFFBQ2QsV0FBVztBQUFBLE1BQ2I7QUFBQSxNQUNBO0FBQUEsUUFDRSxjQUFjO0FBQUEsUUFDZCxXQUFXO0FBQUEsTUFDYjtBQUFBLE1BQ0E7QUFBQSxRQUNFLGNBQWM7QUFBQSxRQUNkLFdBQVc7QUFBQSxNQUNiO0FBQUEsTUFDQTtBQUFBLFFBQ0UsY0FBYztBQUFBLFFBQ2QsV0FBVztBQUFBLE1BQ2I7QUFBQSxNQUNBO0FBQUEsUUFDRSxjQUFjO0FBQUEsUUFDZCxXQUFXO0FBQUEsTUFDYjtBQUFBLE1BQ0E7QUFBQSxRQUNFLGNBQWM7QUFBQSxRQUNkLFdBQVc7QUFBQSxNQUNiO0FBQUEsTUFDQTtBQUFBLFFBQ0UsY0FBYztBQUFBLFFBQ2QsV0FBVztBQUFBLE1BQ2I7QUFBQSxNQUNBO0FBQUEsUUFDRSxjQUFjO0FBQUEsUUFDZCxXQUFXO0FBQUEsTUFDYjtBQUFBLE1BQ0E7QUFBQSxRQUNFLGNBQWM7QUFBQSxRQUNkLFdBQVc7QUFBQSxNQUNiO0FBQUEsSUFDRjtBQUFBLElBQ0EsMEJBQTBCO0FBQUEsSUFDMUIsV0FBVztBQUFBLEVBQ2I7IiwKICAibmFtZXMiOiBbXQp9Cg==
