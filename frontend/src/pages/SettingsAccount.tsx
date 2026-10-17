import { useAuth0 } from '@auth0/auth0-react'
import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import { signedOutUrl } from '../site'

/** Deleting the account: everything Stoke holds for the writer, behind an inline confirm. */
export function DeleteAccount() {
  const { logout } = useAuth0()
  const [confirming, setConfirming] = useState(false)
  const remove = useMutation({
    mutationFn: api.deleteMe,
    onSuccess: () => logout({ logoutParams: { returnTo: signedOutUrl() } }),
  })
  return (
    <section className="settings-section full">
      <h2 id="account">Delete your account</h2>
      <p className="muted lede-small">
        Removes your Stripe connections, the customer data Stoke imported, your free-subscriber lists, notes and
        settings, and disconnects Gmail. This can’t be undone.
      </p>
      {confirming ? (
        <div className="inline-form">
          <span>
            Delete your Stoke account and everything in it? To stop Stripe’s access too, also uninstall Stoke from
            your Stripe Dashboard’s installed apps.
          </span>
          <button className="danger" onClick={() => remove.mutate()} disabled={remove.isPending}>
            {remove.isPending ? 'Deleting…' : 'Delete account'}
          </button>
          <button className="ghost" onClick={() => setConfirming(false)}>
            Cancel
          </button>
          {remove.isError && <p className="error">{remove.error.message}</p>}
        </div>
      ) : (
        <p>
          <button className="link danger" onClick={() => setConfirming(true)}>
            Delete account…
          </button>
        </p>
      )}
    </section>
  )
}
