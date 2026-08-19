import { createBrowserRouter, replace } from "react-router";
import { RouterProvider } from "react-router/dom";

import { ChatIndexPage } from "@/pages/chat/ChatIndexPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { RouteErrorPage } from "@/pages/RouteErrorPage";

const router = createBrowserRouter([
  {
    path: "/",
    ErrorBoundary: RouteErrorPage,
    children: [
      { index: true, loader: () => replace("/chats") },
      { path: "chats", Component: ChatIndexPage },
      { path: "*", Component: NotFoundPage },
    ],
  },
]);

if (import.meta.hot) {
  import.meta.hot.dispose(() => router.dispose());
}

export default function App() {
  return <RouterProvider router={router} />;
}
