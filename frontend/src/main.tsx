import { createRoot } from "react-dom/client";
import { ChatScreen } from "./chat/ChatScreen";
import "./styles/tokens.css";
import "./styles/chat.css";
const root = document.getElementById("root");
if (root) createRoot(root).render(<ChatScreen />);
