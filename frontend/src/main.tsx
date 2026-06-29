import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { router } from "./app/router";
import { ThemeProvider } from "./app/theme";
import { ToastProvider } from "./app/toast";
import { StoreProvider } from "./app/store";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <StoreProvider>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </StoreProvider>
    </ThemeProvider>
  </React.StrictMode>
);
